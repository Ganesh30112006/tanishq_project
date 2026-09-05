"""Advance a registered model through its governed lifecycle (spec section 54).

Every transition needs a named actor and a reason, and they are recorded as a
``ModelLifecycleEvent`` plus an audit row - exactly as the API does it. This
command is the operator-side equivalent for local / controlled environments.

Examples::

    python manage.py govern_model --model cvd-logreg --version 1.0.0 \\
        --to VALIDATION --by admin@example.com --reason "tech validation started"

    python manage.py govern_model --model cvd-logreg --version 1.0.0 \\
        --to APPROVED_FOR_CLINICAL_REVIEW --by cmo@example.com \\
        --reason "clinical governance board sign-off #2024-07" --activate-task
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.common.enums import ModelLifecycleState
from apps.common.errors import AppError
from apps.risk.governance import ModelGovernanceService
from apps.risk.models import ModelVersion


class Command(BaseCommand):
    help = "Move a ModelVersion through its governed lifecycle."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--model", required=True, help="model_id")
        parser.add_argument("--model-version", required=True, dest="model_version")
        parser.add_argument("--to", required=True, choices=ModelLifecycleState.values)
        parser.add_argument("--by", required=True, help="email of the approving user")
        parser.add_argument("--reason", required=True)
        parser.add_argument(
            "--activate-task",
            action="store_true",
            help="On APPROVED_FOR_CLINICAL_REVIEW, also enable this version for its task.",
        )

    def handle(self, *args, **options) -> None:
        model_version = (
            ModelVersion.objects.filter(
                model_id=options["model"], version=options["model_version"]
            )
            .select_related("feature_schema")
            .first()
        )
        if model_version is None:
            raise CommandError(
                f"No ModelVersion {options['model']}:{options['model_version']}."
            )

        actor = get_user_model().objects.filter(email=options["by"]).first()
        if actor is None:
            raise CommandError(f"No user with email {options['by']!r}.")

        service = ModelGovernanceService()
        try:
            model_version = service.transition(
                model_version=model_version,
                to_state=options["to"],
                actor=actor,
                reason=options["reason"],
            )
            if (
                options["activate_task"]
                and model_version.lifecycle_state
                == ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW
            ):
                service.activate_for_task(
                    task=model_version.task, model_version=model_version, actor=actor
                )
        except AppError as exc:
            raise CommandError(
                f"{exc.code}: {exc.message} {exc.details or ''}".strip()
            ) from exc

        self.stdout.write(
            f"{model_version} is now {model_version.lifecycle_state}"
            + (" and ACTIVE for its task." if options["activate_task"] else ".")
        )
