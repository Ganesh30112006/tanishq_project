"""The platform must be able to return 'Prediction unavailable' as a SUCCESSFUL
SAFE OUTCOME (spec section 57)."""
from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.common.enums import ClinicalDataState, ModelLifecycleState
from apps.risk.models import FeatureSchema, ModelVersion, RiskAssessment, RiskModel
from apps.risk.services import RiskAssessmentService
from apps.risk.sufficiency import FeatureValue

pytestmark = pytest.mark.django_db


class _StubClient:
    def __init__(self):
        self.called = False

    def infer(self, **kwargs):  # pragma: no cover - must not be reached
        self.called = True
        raise AssertionError("intelligence service must not be called when data is insufficient")


def _enable_task(task="cvd"):
    schema = FeatureSchema.objects.create(
        task=task,
        version="fs-1",
        definition={
            "required_features": [{"name": "glucose", "max_age_days": 90}],
            "minimum_completeness": 1.0,
            "valid_domain": {},
        },
    )
    mv = ModelVersion.objects.create(
        model_id=f"{task}-model", name="CVD", version="1.0.0", task=task,
        feature_schema=schema,
        lifecycle_state=ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW,
    )
    RiskModel.objects.create(task=task, active_version=mv, is_enabled=True)
    return mv


def test_insufficient_data_blocks_without_calling_model(make_patient, make_user):
    _enable_task()
    stub = _StubClient()
    service = RiskAssessmentService(client=stub)

    result = service.assess(
        patient=make_patient(),
        task="cvd",
        requested_by=make_user(),
        features={
            "glucose": FeatureValue("glucose", None, ClinicalDataState.NOT_REPORTED, None)
        },
        correlation_id="corr-1",
    )

    assert result.failed
    assert result.code == "INSUFFICIENT_DATA"
    assert not stub.called
    stored = RiskAssessment.objects.get()
    assert stored.status == RiskAssessment.Status.BLOCKED
    assert stored.outcome_code == "INSUFFICIENT_DATA"


def test_no_active_model_is_a_safe_block(make_patient, make_user):
    service = RiskAssessmentService(client=_StubClient())
    result = service.assess(
        patient=make_patient(),
        task="undefined-task",
        requested_by=make_user(),
        features={},
        correlation_id="corr-2",
    )
    assert result.failed
    assert result.code == "MODEL_UNAVAILABLE"


def test_reliability_block_from_model_is_persisted(make_patient, make_user):
    mv = _enable_task("dm")
    now = timezone.now()

    class OODClient:
        def infer(self, **kwargs):
            from apps.common.intelligence import InferenceResult

            return InferenceResult(
                raw_score=None, calibrated_score=None, calibration_version="",
                reliability_status="OUT_OF_DOMAIN", reliability_detail={"features": ["glucose"]},
                shap=[], model_echo={},
            )

    result = RiskAssessmentService(client=OODClient()).assess(
        patient=make_patient(),
        task="dm",
        requested_by=make_user(),
        features={"glucose": FeatureValue("glucose", 5.4, ClinicalDataState.OBSERVED, now)},
        correlation_id="corr-3",
    )
    assert result.failed
    assert result.code == "PREDICTION_BLOCKED"
    assert RiskAssessment.objects.get().outcome_code == "OUT_OF_DOMAIN"
