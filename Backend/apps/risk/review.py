"""Clinician review of model outputs (spec sections 39, 40, 57).

A completed risk assessment is *decision support*, not a clinical conclusion.
It stays in ``REVIEW_REQUIRED`` until a clinician records a decision here, at
which point it becomes ``CLINICALLY_REVIEWED`` and then ``FINALIZED``. The
model's number is never replaced by the review - both are kept.
"""
from __future__ import annotations

from django.db import transaction

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import AssessmentLifecycleState, ClinicalReviewDecision
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.risk.models import ClinicalReview, RiskAssessment

_REVIEWABLE_STATES = {
    AssessmentLifecycleState.REVIEW_REQUIRED,
    AssessmentLifecycleState.INSUFFICIENT_DATA,
    AssessmentLifecycleState.CLINICALLY_REVIEWED,
}


class ClinicalReviewService(BaseService):
    @transaction.atomic
    def submit(
        self,
        *,
        assessment: RiskAssessment,
        reviewer,
        decision: str,
        rationale: str,
    ) -> ClinicalReview:
        if decision not in ClinicalReviewDecision.values:
            raise ValidationFailed(f"Unknown review decision {decision!r}.")
        if not (rationale or "").strip():
            raise ValidationFailed("A review rationale is required.")
        if assessment.lifecycle_state not in _REVIEWABLE_STATES:
            raise ValidationFailed(
                "This assessment is not in a reviewable state.",
                details={"lifecycle_state": assessment.lifecycle_state},
            )

        review = ClinicalReview.objects.create(
            assessment=assessment,
            reviewer=reviewer,
            decision=decision,
            rationale=rationale.strip(),
            source_evidence={
                "status": assessment.status,
                "outcome_code": assessment.outcome_code,
                "calibrated_score": (
                    str(assessment.calibrated_score)
                    if assessment.calibrated_score is not None
                    else None
                ),
                "sufficiency": assessment.sufficiency,
                "reliability_status": assessment.reliability_status,
                "limitations": assessment.limitations,
                "model_version": (
                    str(assessment.model_version.public_id)
                    if assessment.model_version_id
                    else None
                ),
            },
        )

        # ACCEPTED / REJECTED are the clinician's final word on this artifact;
        # NEEDS_MORE_DATA / ESCALATED keep it open for another look.
        terminal = decision in {
            ClinicalReviewDecision.ACCEPTED,
            ClinicalReviewDecision.REJECTED,
        }
        new_state = (
            AssessmentLifecycleState.FINALIZED
            if terminal
            else AssessmentLifecycleState.REVIEW_REQUIRED
        )
        RiskAssessment.objects.filter(pk=assessment.pk).update(lifecycle_state=new_state)
        assessment.refresh_from_db(fields=["lifecycle_state"])

        audit_service.record(
            audit.CLINICAL_REVIEW,
            actor=reviewer,
            resource=assessment,
            metadata={"decision": decision, "lifecycle_state": assessment.lifecycle_state},
        )
        return review
