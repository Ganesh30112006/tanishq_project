"""Clinical model governance (spec sections 4, 5, 54, 55).

A model does not become usable because its tests pass. It becomes usable
because a human approver moved it through this lifecycle, and every move is
recorded with who, when, why and against what evidence::

    DRAFT
      -> VALIDATION                     (technical validation begins)
      -> APPROVED_FOR_EVALUATION        (shadow / silent running only)
      -> APPROVED_FOR_CLINICAL_REVIEW   (may back a live task)
      -> RETIRED
    (any non-terminal state) -> REJECTED

This module is the ONLY place ``ModelVersion.lifecycle_state`` changes, and
the only place a task's ``RiskModel`` may be enabled.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import ModelLifecycleState as S
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.risk.models import (
    ModelLifecycleEvent,
    ModelVersion,
    RiskModel,
    missing_intended_use_keys,
)

# Legal transitions. Anything not listed here is refused.
_ALLOWED: dict[str, set[str]] = {
    S.DRAFT: {S.VALIDATION, S.REJECTED},
    S.VALIDATION: {S.APPROVED_FOR_EVALUATION, S.DRAFT, S.REJECTED},
    S.APPROVED_FOR_EVALUATION: {S.APPROVED_FOR_CLINICAL_REVIEW, S.VALIDATION, S.REJECTED},
    S.APPROVED_FOR_CLINICAL_REVIEW: {S.RETIRED, S.REJECTED},
    S.REJECTED: set(),
    S.RETIRED: set(),
}

# Transitions that assert clinical fitness and therefore need a named approver.
_APPROVAL_STATES = {S.APPROVED_FOR_EVALUATION, S.APPROVED_FOR_CLINICAL_REVIEW}


class ModelGovernanceService(BaseService):
    @transaction.atomic
    def transition(
        self,
        *,
        model_version: ModelVersion,
        to_state: str,
        actor,
        reason: str,
        evidence: dict | None = None,
    ) -> ModelVersion:
        frm = model_version.lifecycle_state
        if to_state not in set(S.values):
            raise ValidationFailed(f"Unknown lifecycle state {to_state!r}.")
        if to_state not in _ALLOWED.get(frm, set()):
            raise ValidationFailed(
                f"Illegal model transition {frm} -> {to_state}.",
                details={"allowed": sorted(_ALLOWED.get(frm, set()))},
            )
        if not (reason or "").strip():
            raise ValidationFailed("A transition reason is required.")

        # Leaving DRAFT requires a complete intended-use definition (spec §4).
        if frm == S.DRAFT and to_state == S.VALIDATION:
            gaps = missing_intended_use_keys(model_version.intended_use)
            if gaps:
                raise ValidationFailed(
                    "The intended-use definition is incomplete.",
                    details={"missing_intended_use_keys": gaps},
                )

        # Clinical-review approval additionally requires recorded validation
        # evidence and at least one subgroup breakdown (spec §26, §27, §55).
        if to_state == S.APPROVED_FOR_CLINICAL_REVIEW:
            problems = []
            if not model_version.validation_metrics:
                problems.append("validation_metrics is empty")
            if not model_version.subgroup_metrics:
                problems.append("subgroup_metrics is empty")
            if not model_version.calibration_version:
                problems.append("calibration_version is not set")
            if problems:
                raise ValidationFailed(
                    "The model is not ready for clinical-review approval.",
                    details={"problems": problems},
                )

        model_version.lifecycle_state = to_state
        if to_state in _APPROVAL_STATES:
            model_version.approved_by = actor
            model_version.approved_at = timezone.now()
        if to_state == S.REJECTED:
            model_version.rejected_at = timezone.now()
        if to_state == S.RETIRED:
            model_version.retired_at = timezone.now()
        model_version.save(
            update_fields=[
                "lifecycle_state", "approved_by", "approved_at",
                "rejected_at", "retired_at", "updated_at",
            ]
        )

        # Retiring or rejecting a version that currently backs a task takes it
        # offline immediately - historical predictions are untouched (spec §54).
        if to_state in {S.RETIRED, S.REJECTED}:
            RiskModel.objects.filter(active_version=model_version).update(is_enabled=False)

        event = ModelLifecycleEvent.objects.create(
            model_version=model_version,
            from_state=frm,
            to_state=to_state,
            actor=actor,
            reason=reason.strip(),
            evidence=evidence or {},
        )
        audit_service.record(
            audit.MODEL_GOVERNANCE,
            actor=actor,
            resource=event,
            metadata={
                "model_version": str(model_version.public_id),
                "from": frm,
                "to": to_state,
            },
        )
        return model_version

    @transaction.atomic
    def activate_for_task(self, *, task: str, model_version: ModelVersion, actor) -> RiskModel:
        """Point a task at an approved model version and enable it."""
        if not model_version.is_clinically_approved:
            raise ValidationFailed(
                "Only an APPROVED_FOR_CLINICAL_REVIEW model version can back a live task.",
                details={"lifecycle_state": model_version.lifecycle_state},
            )
        if model_version.task != task:
            raise ValidationFailed("The model version was not built for this task.")
        risk_model, _ = RiskModel.objects.update_or_create(
            task=task,
            defaults={"active_version": model_version, "is_enabled": True},
        )
        audit_service.record(
            audit.MODEL_GOVERNANCE,
            actor=actor,
            resource=risk_model,
            metadata={"action": "activate", "task": task,
                      "model_version": str(model_version.public_id)},
        )
        return risk_model
