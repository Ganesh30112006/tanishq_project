"""Risk assessment orchestration (spec sections 28, 31, 32, 34, 35, 57).

Authorization and authorized-data retrieval happen in the calling view/service
(Django owns patient scope). This service:

1. resolves the active model for the task;
2. runs the deterministic sufficiency check;
3. if sufficient, sends ONLY the validated feature payload + model/task ids +
   correlation id to the FastAPI intelligence service;
4. applies the reliability / OOD verdict;
5. persists a fully version-stamped, append-only assessment (+ SHAP factors);
6. returns a :class:`ServiceResult` - "Prediction unavailable" is a success.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import AssessmentLifecycleState, DataSufficiency, ReliabilityStatus
from apps.common.intelligence import IntelligenceClient
from apps.common.services import BaseService, ServiceResult
from apps.risk.models import ModelVersion, RiskAssessment, RiskFactor, RiskModel
from apps.risk.sufficiency import DataSufficiencyEngine, FeatureValue

_BLOCKING_RELIABILITY = {
    ReliabilityStatus.OUT_OF_DOMAIN,
    ReliabilityStatus.INSUFFICIENT_DATA,
    ReliabilityStatus.REVIEW_REQUIRED,
}


class RiskAssessmentService(BaseService):
    def __init__(self, *, client: IntelligenceClient | None = None) -> None:
        self.client = client or IntelligenceClient()
        self.sufficiency = DataSufficiencyEngine()

    def assess(
        self,
        *,
        patient,
        task: str,
        requested_by,
        features: dict[str, FeatureValue],
        correlation_id: str,
    ) -> ServiceResult[RiskAssessment]:
        # Not one outer transaction: ``self.client.infer`` below is a network
        # call to the intelligence service and must never run with a database
        # transaction held open around it. Each persistence step below is
        # its own short atomic block instead.
        model_cfg = RiskModel.objects.select_related(
            "active_version", "active_version__feature_schema"
        ).filter(task=task).first()

        if model_cfg is None or not model_cfg.is_enabled or model_cfg.active_version is None:
            assessment = self._blocked(
                patient, requested_by, task, None, "MODEL_UNAVAILABLE", correlation_id,
                lifecycle_state=AssessmentLifecycleState.CANCELLED,
            )
            return ServiceResult.blocked(
                "MODEL_UNAVAILABLE", "No active model for this task.", value=assessment
            )

        model: ModelVersion = model_cfg.active_version
        schema = model.feature_schema

        report = self.sufficiency.evaluate(definition=schema.definition, features=features)
        if not report.is_sufficient:
            assessment = self._blocked(
                patient,
                requested_by,
                task,
                model,
                report.outcome_code(),
                correlation_id,
                sufficiency=report.status,
                missing=report.missing + report.stale + report.invalid,
                conflicts=report.conflicting,
                lifecycle_state=AssessmentLifecycleState.INSUFFICIENT_DATA,
                limitations=self._limitations(model, sufficiency=report.status),
            )
            audit_service.record(
                audit.RISK_ASSESSMENT, actor=requested_by, resource=assessment,
                metadata={"outcome": report.outcome_code(), "task": task},
            )
            return ServiceResult.blocked(
                report.outcome_code(),
                "Data is not sufficient for a reliable prediction.",
                value=assessment,
                details={
                    "missing": report.missing,
                    "stale": report.stale,
                    "conflicts": report.conflicting,
                },
            )

        payload = {name: _num(fv.value) for name, fv in features.items() if fv.value is not None}
        result = self.client.infer(
            task=task,
            model_version=model.version,
            feature_schema_version=schema.version,
            features=payload,
            correlation_id=correlation_id,
        )

        if result.reliability_status in _BLOCKING_RELIABILITY:
            assessment = self._blocked(
                patient, requested_by, task, model, result.reliability_status, correlation_id,
                sufficiency=DataSufficiency.SUFFICIENT, reliability=result.reliability_status,
                lifecycle_state=AssessmentLifecycleState.INSUFFICIENT_DATA,
                limitations=self._limitations(model, reliability=result.reliability_status),
            )
            audit_service.record(
                audit.RISK_ASSESSMENT, actor=requested_by, resource=assessment,
                metadata={"outcome": result.reliability_status, "task": task},
            )
            return ServiceResult.blocked(
                "PREDICTION_BLOCKED",
                "The model declined to produce a reliable prediction for this input.",
                value=assessment,
                details={"reliability": result.reliability_detail},
            )

        with transaction.atomic():
            assessment = RiskAssessment.objects.create(
                patient=patient,
                requested_by=requested_by,
                task=task,
                model_version=model,
                feature_schema_version=schema.version,
                preprocessing_version=model.preprocessing_version,
                calibration_version=result.calibration_version or model.calibration_version,
                explanation_version=model.explanation_version,
                status=RiskAssessment.Status.COMPLETED,
                # A produced prediction is decision support awaiting a
                # clinician - never an automatically finalized result
                # (spec sections 39, 40, 57).
                lifecycle_state=AssessmentLifecycleState.REVIEW_REQUIRED,
                outcome_code="OK",
                sufficiency=DataSufficiency.SUFFICIENT,
                reliability_status=result.reliability_status or ReliabilityStatus.VALID,
                raw_score=_dec(result.raw_score),
                calibrated_score=_dec(result.calibrated_score),
                limitations=self._limitations(
                    model, reliability=result.reliability_status or ReliabilityStatus.VALID
                ),
                input_snapshot=payload,
                correlation_id=correlation_id,
            )
            self._store_factors(assessment, result.shap)
            audit_service.record(
                audit.RISK_ASSESSMENT, actor=requested_by, resource=assessment,
                metadata={"outcome": "OK", "task": task, "model_version": model.version},
            )
        return ServiceResult.success(assessment)

    # ------------------------------------------------------------------
    @transaction.atomic
    def _blocked(
        self, patient, requested_by, task, model, outcome, correlation_id,
        *, sufficiency="", reliability="", missing=None, conflicts=None,
        lifecycle_state=AssessmentLifecycleState.INSUFFICIENT_DATA, limitations=None,
    ) -> RiskAssessment:
        return RiskAssessment.objects.create(
            patient=patient,
            requested_by=requested_by,
            task=task,
            model_version=model,
            feature_schema_version=getattr(getattr(model, "feature_schema", None), "version", ""),
            status=RiskAssessment.Status.BLOCKED,
            lifecycle_state=lifecycle_state,
            outcome_code=outcome,
            sufficiency=sufficiency,
            reliability_status=reliability,
            limitations=limitations or [],
            input_snapshot={},
            missing_features=missing or [],
            conflicts=conflicts or [],
            correlation_id=correlation_id,
        )

    @staticmethod
    def _limitations(model, *, sufficiency: str = "", reliability: str = "") -> list[str]:
        """Compose the structured limitation strings surfaced with a result
        (spec section 58). Model-card limitations first, then anything specific
        to this request."""
        out: list[str] = []
        if model is not None:
            out.extend(model.structured_limitations())
        if sufficiency == DataSufficiency.PARTIALLY_SUFFICIENT:
            out.append("Some required evidence was missing, stale or invalid for this patient.")
        if reliability == ReliabilityStatus.LOW_RELIABILITY:
            out.append("The input is near the edge of the model's validated domain.")
        return out

    def _store_factors(self, assessment: RiskAssessment, shap: list[dict]) -> None:
        rows = []
        for rank, item in enumerate(shap, start=1):
            contribution = _dec(item.get("contribution")) or Decimal("0")
            rows.append(
                RiskFactor(
                    assessment=assessment,
                    feature_name=str(item.get("feature", ""))[:120],
                    contribution=contribution,
                    direction=(
                        RiskFactor.Direction.INCREASES
                        if contribution >= 0
                        else RiskFactor.Direction.DECREASES
                    ),
                    rank=rank,
                )
            )
        RiskFactor.objects.bulk_create(rows)


def _num(value: object) -> float:
    return float(value)  # type: ignore[arg-type]


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
