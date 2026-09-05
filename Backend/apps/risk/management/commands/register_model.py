"""Register a trained model artifact in the Django model registry.

Reads the ``<task>-<version>.meta.json`` emitted by
``intelligence.ml_service.train`` and creates/updates the matching
``FeatureSchema`` + ``ModelVersion`` rows.

The version is always registered in ``DRAFT``. It does NOT become usable here:
moving it through the governed lifecycle (and pointing a task at it) is done
with ``manage.py govern_model`` or the ``/api/v1/risk/models`` API, so that a
named approver and a recorded reason always stand behind a live clinical model
(spec sections 5, 54).

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
        definition = {
            "required_features": required,
            "optional_features": [],
            "minimum_completeness": 1.0,
            "max_data_age_days": meta.get("max_data_age_days", 365),
            "valid_domain": meta["domain"],
        }
        schema, _ = FeatureSchema.objects.update_or_create(
            task=meta["task"],
            version=meta["feature_schema_version"],
            defaults={"definition": definition},
        )

        model_version, created = ModelVersion.objects.update_or_create(
            model_id=meta["model_id"],
            version=meta["model_version"],
            defaults={
                "name": meta["name"],
                "task": meta["task"],
                "model_type": meta.get("model_type", ""),
                "prediction_target": meta.get("prediction_target", ""),
                "feature_schema": schema,
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
                "lifecycle_state": ModelLifecycleState.DRAFT,
            },
        )

        verb = "Created" if created else "Updated"
        self.stdout.write(
            f"{verb} {model_version} (schema {schema}). "
            f"Registered as DRAFT - use `govern_model` to advance it."
        )
