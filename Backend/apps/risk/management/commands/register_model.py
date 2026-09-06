"""Register a trained model artifact in the Django model registry.

Reads the ``<task>-<version>.meta.json`` emitted by
``intelligence.ml_service.train`` and creates/updates the matching
``FeatureSchema`` + ``ModelVersion`` rows.

The version is always registered in ``DRAFT``. It does NOT become usable here:
moving it through the governed lifecycle (and pointing a task at it) is done
with ``manage.py govern_model`` or the ``/api/v1/risk/models`` API, so that a
named approver and a recorded reason always stand behind a live clinical model
(spec sections 5, 54).

**A version that has left DRAFT is immutable.** This command used to
``update_or_create`` with ``lifecycle_state=DRAFT`` in the defaults, which meant
re-running it silently reset any existing version back to DRAFT and overwrote
its weights, domain and metrics. Two things were broken by that. RETIRED stopped
being terminal - a model withdrawn from service could be brought back by
re-registering it - and, worse, a version identifier stopped meaning anything: a
``RiskAssessment`` row recorded months ago naming ``cvd-nhanes-logreg:3.0.0``
could end up pointing at a registry row describing an entirely different model,
with different features and different validation numbers. An audit trail that
can be rewritten from the outside is not an audit trail.

A changed model needs a new version number. Re-registering a byte-identical
version is a no-op, so re-running a provisioning script stays safe.

Usage::

    python manage.py register_model --meta intelligence/_artifacts/cvd-1.0.0.meta.json
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.common.enums import ModelLifecycleState
from apps.risk.models import FeatureSchema, ModelVersion


class Command(BaseCommand):
    help = "Register a trained model artifact from its meta.json sidecar (as DRAFT)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--meta", required=True, help="Path to <task>-<version>.meta.json")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        meta_path = Path(options["meta"])
        if not meta_path.exists():
            raise CommandError(f"Meta file not found: {meta_path}")
        meta = json.loads(meta_path.read_text())

        required = [
            {"name": name, "max_age_days": meta.get("max_data_age_days", 365)}
            for name in meta["feature_order"]
        ]
        # Which direction each feature moves risk in, taken from the fitted
        # standardised coefficients. The sufficiency engine needs this to tell
        # a dangerous out-of-domain reading from a harmless one: a blood
        # pressure above the validated ceiling and one below the floor are both
        # "out of domain", but only one of them is the record's most alarming
        # number. Sign only - the magnitude is never shown to anyone from here.
        coefficients = (meta.get("validation_metrics") or {}).get(
            "standardised_coefficients", {}
        )
        risk_direction = {
            name: (1 if float(value) > 0 else -1 if float(value) < 0 else 0)
            for name, value in coefficients.items()
            if name in meta["feature_order"]
        }
        definition = {
            "required_features": required,
            "optional_features": [],
            "minimum_completeness": 1.0,
            "max_data_age_days": meta.get("max_data_age_days", 365),
            "valid_domain": meta["domain"],
            "risk_direction": risk_direction,
        }
        # The evidence dossier sits beside the model card and is deliberately
        # NOT part of the immutable comparison below. The model is fixed; the
        # evidence about it is not, and is meant to accumulate - a validation
        # run on a new cohort next year adds to what is known without changing
        # a single weight. Freezing the dossier at approval time would make the
        # record permanently claim less than is known.
        #
        # What stops that from becoming a hole is that the gaps acknowledged at
        # approval live in the ModelLifecycleEvent, which is append-only. A
        # later dossier can close a gap; it cannot make it look as though the
        # gap was never there when somebody signed.
        dossier_path = meta_path.with_name(
            f"{meta['task']}-{meta['model_version']}.evidence.json"
        )
        dossier = json.loads(dossier_path.read_text()) if dossier_path.exists() else {}

        existing = ModelVersion.objects.filter(
            model_id=meta["model_id"], version=meta["model_version"]
        ).first()
        fields = {
            "name": meta["name"],
            "task": meta["task"],
            "model_type": meta.get("model_type", ""),
            "prediction_target": meta.get("prediction_target", ""),
            "training_dataset_version": meta.get("training_dataset_version", ""),
            "validation_dataset_version": meta.get("validation_dataset_version", ""),
            "external_validation_dataset_version": meta.get(
                "external_validation_dataset_version", ""
            ),
            "preprocessing_version": meta["preprocessing_version"],
            "calibration_version": meta["calibration_version"],
            "explanation_version": meta["explanation_version"],
            "intended_use": meta.get("intended_use", {}),
            "validation_metrics": meta.get("validation_metrics", {}),
            "subgroup_metrics": meta.get("subgroup_metrics", {}),
            "population_domain": meta.get("population_domain", {}),
            "known_failure_modes": meta.get("known_failure_modes", []),
            "limitations": meta.get("limitations", ""),
        }

        # Decide BEFORE writing anything. The feature schema carries
        # ``valid_domain`` - the gate that refuses to score a patient outside the
        # range the model was fitted on - so it must never be rewritten under an
        # approved version either. The surrounding transaction would roll a bad
        # write back anyway, but a check that depends on a rollback to be correct
        # is one refactor away from not being correct.
        if existing is not None and existing.lifecycle_state != ModelLifecycleState.DRAFT:
            changed = sorted(
                name for name, value in fields.items()
                if name != "feature_schema" and getattr(existing, name) != value
            )
            if existing.feature_schema.definition != definition:
                changed.append("feature_schema.definition")
            if existing.feature_schema.version != meta["feature_schema_version"]:
                changed.append("feature_schema.version")
            if not changed:
                if dossier and existing.evidence_dossier != dossier:
                    existing.evidence_dossier = dossier
                    existing.save(update_fields=["evidence_dossier", "updated_at"])
                    self.stdout.write(
                        f"{existing} is unchanged; updated its evidence dossier "
                        f"({dossier['status_counts']['answered']} answered, "
                        f"{dossier['status_counts']['partial']} partial, "
                        f"{dossier['status_counts']['unanswered']} unanswered)."
                    )
                    return
                self.stdout.write(
                    f"{existing} is already registered and unchanged - nothing to do."
                )
                return
            raise CommandError(
                f"{existing.model_id}:{existing.version} is {existing.lifecycle_state}, "
                f"not DRAFT, and this artifact differs from the registered one "
                f"({', '.join(changed)}). A version that has left DRAFT is immutable: "
                f"every audit record naming this version must keep meaning the model "
                f"that was approved. Train and register a new version number instead."
            )

        schema, _ = FeatureSchema.objects.update_or_create(
            task=meta["task"],
            version=meta["feature_schema_version"],
            defaults={"definition": definition},
        )
        fields["feature_schema"] = schema

        model_version, created = ModelVersion.objects.update_or_create(
            model_id=meta["model_id"],
            version=meta["model_version"],
            defaults={**fields, "evidence_dossier": dossier,
                      "lifecycle_state": ModelLifecycleState.DRAFT},
        )

        verb = "Created" if created else "Updated the DRAFT"
        self.stdout.write(
            f"{verb} {model_version} (schema {schema}). "
            f"Registered as DRAFT - use `govern_model` to advance it."
        )
        if not dossier:
            self.stdout.write(self.style.WARNING(
                f"No evidence dossier at {dossier_path.name}. This version "
                f"cannot be approved for clinical review until one exists - "
                f"run `python -m intelligence.ml_service.evidence "
                f"--version {meta['model_version']}` and register again."
            ))
        else:
            open_questions = model_version.open_evidence_questions()
            if open_questions:
                self.stdout.write(self.style.WARNING(
                    "Open evidence gaps: " + ", ".join(open_questions)
                    + ". An approver must name these to advance this version."
                ))
