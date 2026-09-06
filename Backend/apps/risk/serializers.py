from __future__ import annotations

from rest_framework import serializers

from apps.common.enums import ClinicalReviewDecision, ModelLifecycleState
from apps.risk.freshness import has_new_clinical_input_since
from apps.risk.interpretation import (
    describe_block,
    interpret,
    viewer_sees_raw_output,
)
from apps.risk.models import ClinicalReview, ModelVersion, RiskAssessment, RiskFactor
from apps.risk.safety import urgent_care_notice


class RiskRequestSerializer(serializers.Serializer):
    patient_id = serializers.UUIDField()
    task = serializers.CharField(max_length=80)


class RiskFactorSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskFactor
        fields = ["feature_name", "direction", "contribution", "rank"]
        read_only_fields = fields


class ClinicalReviewSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    reviewer = serializers.CharField(source="reviewer.get_username", read_only=True)

    class Meta:
        model = ClinicalReview
        fields = ["id", "decision", "rationale", "reviewer", "created_at"]
        read_only_fields = fields


class ClinicalReviewCreateSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=ClinicalReviewDecision.choices)
    rationale = serializers.CharField(min_length=3)


class RiskAssessmentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    patient_id = serializers.UUIDField(source="patient.public_id", read_only=True)
    model = serializers.SerializerMethodField()
    factors = RiskFactorSerializer(many=True, read_only=True)
    reviews = ClinicalReviewSerializer(many=True, read_only=True)
    safety_notice = serializers.SerializerMethodField()
    interpretation = serializers.SerializerMethodField()
    blocked_explanation = serializers.SerializerMethodField()
    superseded_by_new_data = serializers.SerializerMethodField()

    class Meta:
        model = RiskAssessment
        fields = [
            "id",
            "patient_id",
            "task",
            "status",
            "lifecycle_state",
            "outcome_code",
            "sufficiency",
            "reliability_status",
            "calibrated_score",
            "raw_score",
            "limitations",
            "model",
            "feature_schema_version",
            "preprocessing_version",
            "calibration_version",
            "explanation_version",
            "missing_features",
            "conflicts",
            "correlation_id",
            "created_at",
            "factors",
            "reviews",
            "safety_notice",
            "interpretation",
            "blocked_explanation",
            "superseded_by_new_data",
        ]
        read_only_fields = fields

    def get_model(self, obj: RiskAssessment) -> str | None:
        if obj.model_version_id is None:
            return None
        return f"{obj.model_version.model_id}:{obj.model_version.version}"

    def to_representation(self, instance: RiskAssessment) -> dict:
        data = super().to_representation(instance)
        # A calibrated probability is only meaningful for a completed prediction.
        if instance.status != RiskAssessment.Status.COMPLETED:
            data["calibrated_score"] = None
            data["raw_score"] = None
        return data


    def get_safety_notice(self, obj) -> dict | None:
        """Urgent-symptom guidance for an elevated band.

        Attached server-side so it cannot be lost by a client that forgets to
        render it, and so the wording is identical everywhere.
        """
        if obj.status != obj.Status.COMPLETED:
            return None
        return urgent_care_notice(obj.calibrated_score)


    # -- patient-facing reading of the result ---------------------------
    def _viewer_is_clinician(self) -> bool:
        request = self.context.get("request")
        return viewer_sees_raw_output(getattr(request, "user", None))

    def get_interpretation(self, obj) -> dict | None:
        return interpret(obj, for_clinician=self._viewer_is_clinician())

    def get_blocked_explanation(self, obj) -> dict | None:
        """What a safe refusal means, and what would resolve it."""
        return describe_block(obj)

    def get_superseded_by_new_data(self, obj) -> bool:
        """True when results have been recorded since this was calculated.

        A figure computed before someone's latest test should not be read as
        current, so the reader is told rather than left to assume.
        """
        return has_new_clinical_input_since(obj.patient, obj.created_at)


class ModelVersionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    approved_by = serializers.CharField(
        source="approved_by.get_username", read_only=True, default=None
    )
    feature_schema = serializers.SerializerMethodField()
    # Exposed beside the dossier so a caller reading this over the API sees the
    # gaps without having to re-implement the rule that finds them. A client
    # that has to derive "what is still unknown" for itself will eventually get
    # it wrong, and it will get it wrong in the reassuring direction.
    open_evidence_questions = serializers.SerializerMethodField()

    def get_feature_schema(self, obj: ModelVersion) -> str:
        return f"{obj.feature_schema.task}/{obj.feature_schema.version}"

    def get_open_evidence_questions(self, obj: ModelVersion) -> list:
        return obj.open_evidence_questions()

    class Meta:
        model = ModelVersion
        fields = [
            "id",
            "model_id",
            "name",
            "version",
            "task",
            "model_type",
            "prediction_target",
            "lifecycle_state",
            "feature_schema",
            "training_dataset_version",
            "validation_dataset_version",
            "external_validation_dataset_version",
            "preprocessing_version",
            "calibration_version",
            "explanation_version",
            "intended_use",
            "validation_metrics",
            "subgroup_metrics",
            "population_domain",
            "known_failure_modes",
            "limitations",
            "evidence_dossier",
            "open_evidence_questions",
            "approved_by",
            "approved_at",
            "rejected_at",
            "retired_at",
            "created_at",
        ]
        read_only_fields = fields


class ModelTransitionSerializer(serializers.Serializer):
    to_state = serializers.ChoiceField(choices=ModelLifecycleState.choices)
    reason = serializers.CharField(min_length=3)
    evidence = serializers.DictField(
        required=False,
        default=dict,
        help_text="Supporting evidence for this decision. Approving a version "
        "for clinical review requires 'acknowledged_evidence_gaps': the list of "
        "evidence-dossier question keys that are still open, taken from the "
        "version's open_evidence_questions. Gaps do not block approval; "
        "approving without naming them does.",
    )
    activate_task = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When transitioning to APPROVED_FOR_CLINICAL_REVIEW, also point "
        "the task's live model at this version.",
    )
