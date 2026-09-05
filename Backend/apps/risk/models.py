"""Model registry, feature schemas and reproducible risk assessments.

Every prediction identifies the exact model version and every version-stamped
input needed to reproduce it later (spec sections 33, 34). Assessments are
append-only; a re-run is a new row.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import (
    AssessmentLifecycleState,
    ClinicalReviewDecision,
    DataSufficiency,
    ModelLifecycleState,
    ReliabilityStatus,
)
from apps.common.models import AppendOnlyModel, UUIDTimeStampedModel
from apps.patients.models import Patient

# Keys an intended-use definition must carry before a model may leave DRAFT
# (spec section 4). Values may be strings or lists; only presence is enforced
# here - clinical adequacy of the content is a human governance judgement.
REQUIRED_INTENDED_USE_KEYS = (
    "intended_use",
    "target_population",
    "inclusion_criteria",
    "exclusion_criteria",
    "prediction_target",
    "prediction_horizon",
    "input_requirements",
    "required_data_quality",
    "acceptable_data_freshness",
    "validated_domain",
    "known_limitations",
    "output_interpretation",
    "contraindications",
    "review_requirements",
)


def missing_intended_use_keys(intended_use: dict) -> list[str]:
    """Return the required intended-use keys that are absent or empty."""
    intended_use = intended_use or {}
    return [
        key
        for key in REQUIRED_INTENDED_USE_KEYS
        if key not in intended_use
        or intended_use[key] in (None, "", [], {})
    ]


class FeatureSchema(UUIDTimeStampedModel):
    """Defines what a task needs from the record (spec section 24)."""

    task = models.CharField(max_length=80)
    version = models.CharField(max_length=32)
    # definition keys:
    #   required_features: [{name, kind, min?, max?, max_age_days}]
    #   optional_features: [...]
    #   minimum_completeness: 0..1 (fraction of required present & valid)
    #   max_data_age_days: int
    #   valid_domain: {feature: {min, max}}
    #   missingness_constraints, conflicting_data_constraints
    definition = models.JSONField(default=dict)

    class Meta:
        db_table = "risk_feature_schema"
        constraints = [
            models.UniqueConstraint(fields=["task", "version"], name="uq_feature_schema_version")
        ]

    def __str__(self) -> str:
        return f"{self.task}/{self.version}"


class ModelVersion(UUIDTimeStampedModel):
    """A single governed version of a clinical prediction model (spec sections
    5, 43, 54).

    ``lifecycle_state`` is the only thing that decides whether this version may
    back a live task. It is moved solely by
    :class:`~apps.risk.governance.ModelGovernanceService`, never by editing a
    row directly, and every transition records the approver, time and reason.
    """

    model_id = models.CharField(max_length=80)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=32)
    model_type = models.CharField(max_length=80, blank=True)
    task = models.CharField(max_length=80)
    prediction_target = models.CharField(max_length=200, blank=True)

    feature_schema = models.ForeignKey(
        FeatureSchema, on_delete=models.PROTECT, related_name="model_versions"
    )
    training_dataset_version = models.CharField(max_length=64, blank=True)
    validation_dataset_version = models.CharField(max_length=64, blank=True)
    external_validation_dataset_version = models.CharField(max_length=64, blank=True)
    preprocessing_version = models.CharField(max_length=64, blank=True)
    calibration_version = models.CharField(max_length=64, blank=True)
    explanation_version = models.CharField(max_length=64, blank=True)

    # Structured clinical intended-use definition (spec section 4). Required to
    # be complete before the version can move past DRAFT.
    intended_use = models.JSONField(default=dict, blank=True)

    validation_metrics = models.JSONField(default=dict, blank=True)
    # Per-subgroup performance so aggregate numbers cannot hide a subgroup the
    # model serves poorly (spec section 55).
    subgroup_metrics = models.JSONField(default=dict, blank=True)
    population_domain = models.JSONField(default=dict, blank=True)
    known_failure_modes = models.JSONField(default=list, blank=True)
    limitations = models.TextField(blank=True)

    lifecycle_state = models.CharField(
        max_length=32,
        choices=ModelLifecycleState.choices,
        default=ModelLifecycleState.DRAFT,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "risk_model_version"
        constraints = [
            models.UniqueConstraint(fields=["model_id", "version"], name="uq_model_version")
        ]

    def __str__(self) -> str:
        return f"{self.model_id}:{self.version} [{self.lifecycle_state}]"

    @property
    def is_clinically_approved(self) -> bool:
        return self.lifecycle_state == ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW

    def structured_limitations(self) -> list[str]:
        """Human-readable limitation strings drawn from the model card, for the
        risk output contract (spec section 58)."""
        out: list[str] = []
        if self.limitations:
            out.append(self.limitations.strip())
        for mode in self.known_failure_modes or []:
            out.append(str(mode))
        if not self.external_validation_dataset_version:
            out.append("No external validation dataset has been recorded for this model.")
        return out


class ModelLifecycleEvent(UUIDTimeStampedModel):
    """Append-only record of every model lifecycle transition (spec section 54)."""

    model_version = models.ForeignKey(
        ModelVersion, on_delete=models.PROTECT, related_name="lifecycle_events"
    )
    from_state = models.CharField(max_length=32, choices=ModelLifecycleState.choices, blank=True)
    to_state = models.CharField(max_length=32, choices=ModelLifecycleState.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.TextField()
    evidence = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "risk_model_lifecycle_event"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.model_version_id}: {self.from_state or '-'} -> {self.to_state}"


class RiskModel(UUIDTimeStampedModel):
    """Binds a task to its currently active model version + feature schema.

    A task may only be *enabled* with an ``active_version`` that has reached
    ``APPROVED_FOR_CLINICAL_REVIEW``; this is enforced in
    :meth:`clean` / :meth:`save` so no code path (command, admin, shell) can
    quietly put an unapproved model in front of clinicians (spec section 5).
    """

    task = models.CharField(max_length=80, unique=True)
    active_version = models.ForeignKey(
        ModelVersion, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    is_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "risk_model"

    def __str__(self) -> str:
        return self.task

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.is_enabled:
            if self.active_version is None:
                raise ValidationError("An enabled task must have an active model version.")
            if not self.active_version.is_clinically_approved:
                raise ValidationError(
                    "The active model version is not APPROVED_FOR_CLINICAL_REVIEW; "
                    "it cannot back an enabled task."
                )

    def save(self, *args: object, **kwargs: object) -> None:
        self.clean()
        super().save(*args, **kwargs)  # type: ignore[arg-type]


class RiskAssessment(AppendOnlyModel):
    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked (safe outcome)"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="risk_assessments")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    task = models.CharField(max_length=80)
    model_version = models.ForeignKey(
        ModelVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="assessments"
    )

    feature_schema_version = models.CharField(max_length=32, blank=True)
    preprocessing_version = models.CharField(max_length=64, blank=True)
    calibration_version = models.CharField(max_length=64, blank=True)
    explanation_version = models.CharField(max_length=64, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices)
    # Where this specific request got to, and whether a clinician still needs
    # to look at it. A COMPLETED prediction is NOT a finalized clinical
    # assessment - it lands in REVIEW_REQUIRED (spec section 40).
    lifecycle_state = models.CharField(
        max_length=32,
        choices=AssessmentLifecycleState.choices,
        default=AssessmentLifecycleState.REQUESTED,
    )
    outcome_code = models.CharField(
        max_length=32, blank=True, help_text="e.g. INSUFFICIENT_DATA, OUT_OF_DOMAIN"
    )
    sufficiency = models.CharField(
        max_length=24, choices=DataSufficiency.choices, blank=True
    )
    reliability_status = models.CharField(
        max_length=20, choices=ReliabilityStatus.choices, blank=True
    )

    raw_score = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    calibrated_score = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Structured limitation strings surfaced with the result (spec section 58).
    limitations = models.JSONField(default=list, blank=True)

    # Snapshot of the exact validated feature payload sent to the model.
    input_snapshot = models.JSONField(default=dict)
    missing_features = models.JSONField(default=list, blank=True)
    conflicts = models.JSONField(default=list, blank=True)
    correlation_id = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "risk_assessment"
        indexes = [models.Index(fields=["patient", "task", "created_at"])]

    def __str__(self) -> str:
        return f"{self.task} for {self.patient_id}: {self.status}/{self.outcome_code}"


class ClinicalReview(AppendOnlyModel):
    """A clinician's recorded decision on a model output (spec section 39).

    Append-only: a changed opinion is a new review row, so the full review
    history of an assessment is preserved.
    """

    assessment = models.ForeignKey(
        RiskAssessment, on_delete=models.PROTECT, related_name="reviews"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="clinical_reviews"
    )
    decision = models.CharField(max_length=20, choices=ClinicalReviewDecision.choices)
    rationale = models.TextField()
    source_evidence = models.JSONField(
        default=dict, blank=True, help_text="Snapshot of what the reviewer saw."
    )

    class Meta:
        db_table = "risk_clinical_review"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"review of {self.assessment_id} by {self.reviewer_id}: {self.decision}"


class RiskFactor(UUIDTimeStampedModel):
    class Direction(models.TextChoices):
        INCREASES = "INCREASES", "Increases risk"
        DECREASES = "DECREASES", "Decreases risk"

    assessment = models.ForeignKey(
        RiskAssessment, on_delete=models.CASCADE, related_name="factors"
    )
    feature_name = models.CharField(max_length=120)
    contribution = models.DecimalField(max_digits=12, decimal_places=8)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    rank = models.PositiveIntegerField()

    class Meta:
        db_table = "risk_factor"
        ordering = ["rank"]
