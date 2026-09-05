"""Assessment lifecycle and clinician review (spec sections 39, 40, 57, 58).

A produced prediction is decision support awaiting a clinician - never an
automatically finalized clinical conclusion.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.common.enums import AssessmentLifecycleState as L
from apps.common.enums import ClinicalDataState, ModelLifecycleState, Role
from apps.common.intelligence import InferenceResult
from apps.laboratories.models import Laboratory, LabOrder, LabResult
from apps.risk.models import ClinicalReview, FeatureSchema, ModelVersion, RiskAssessment, RiskModel

pytestmark = pytest.mark.django_db
TASK = "cvd"


@pytest.fixture
def enabled_task(db):
    schema = FeatureSchema.objects.create(
        task=TASK, version="fs-1",
        definition={
            "required_features": [
                {"name": "age", "max_age_days": 3650},
                {"name": "glucose", "max_age_days": 90},
            ],
            "minimum_completeness": 1.0, "valid_domain": {},
        },
    )
    mv = ModelVersion.objects.create(
        model_id="cvd-model", name="CVD", version="1.0.0", task=TASK,
        feature_schema=schema, calibration_version="cal-1",
        known_failure_modes=["Synthetic training distribution."],
        lifecycle_state=ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW,
    )
    RiskModel.objects.create(task=TASK, active_version=mv, is_enabled=True)
    return mv


def _patient_with_data(make_patient, assign_patient, doctor):
    patient = make_patient()
    patient.date_of_birth = dt.date(1972, 6, 1)
    patient.save(update_fields=["date_of_birth"])
    assign_patient(doctor, patient)
    lab = Laboratory.objects.create(name="Lab", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=Decimal("5.4"),
        unit_normalized="mmol/L", state=ClinicalDataState.OBSERVED,
        observed_at=timezone.now() - dt.timedelta(days=3),
    )
    return patient


def test_completed_prediction_awaits_review_and_carries_limitations(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    monkeypatch.setattr(
        "apps.common.intelligence.IntelligenceClient.infer",
        lambda self, **kw: InferenceResult(
            raw_score=0.2, calibrated_score=0.18, calibration_version="cal-1",
            reliability_status="VALID", reliability_detail={},
            shap=[{"feature": "glucose", "contribution": 0.4}], model_echo={},
        ),
    )
    doctor = make_doctor()
    patient = _patient_with_data(make_patient, assign_patient, doctor)

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK},
        format="json",
    )
    assert resp.status_code == 201
    body = resp.data["assessment"]
    assert body["status"] == "COMPLETED"
    assert body["lifecycle_state"] == L.REVIEW_REQUIRED
    assert any("Synthetic training distribution" in s for s in body["limitations"])
    assert body["reviews"] == []


def test_blocked_prediction_uses_insufficient_data_lifecycle(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    monkeypatch.setattr(
        "apps.common.intelligence.IntelligenceClient.infer",
        lambda self, **kw: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    doctor = make_doctor()
    patient = make_patient()  # no age, no glucose
    assign_patient(doctor, patient)

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["assessment"]["lifecycle_state"] == L.INSUFFICIENT_DATA


def test_doctor_review_accept_finalizes_and_audits(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    monkeypatch.setattr(
        "apps.common.intelligence.IntelligenceClient.infer",
        lambda self, **kw: InferenceResult(
            raw_score=0.2, calibrated_score=0.18, calibration_version="cal-1",
            reliability_status="VALID", reliability_detail={}, shap=[], model_echo={},
        ),
    )
    doctor = make_doctor()
    patient = _patient_with_data(make_patient, assign_patient, doctor)
    client = auth_client(doctor.user)
    created = client.post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK},
        format="json",
    )
    assessment_id = created.data["assessment"]["id"]

    resp = client.post(
        f"/api/v1/risk/assessments/{assessment_id}/review/",
        {"decision": "ACCEPTED", "rationale": "Consistent with the record; will monitor."},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["assessment"]["lifecycle_state"] == L.FINALIZED
    assert resp.data["review"]["decision"] == "ACCEPTED"
    assert ClinicalReview.objects.filter(assessment__public_id=assessment_id).count() == 1
    assert AuditLog.objects.filter(action="clinical.review", result="SUCCESS").exists()


def test_needs_more_data_keeps_assessment_open(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    monkeypatch.setattr(
        "apps.common.intelligence.IntelligenceClient.infer",
        lambda self, **kw: InferenceResult(
            raw_score=0.2, calibrated_score=0.18, calibration_version="cal-1",
            reliability_status="VALID", reliability_detail={}, shap=[], model_echo={},
        ),
    )
    doctor = make_doctor()
    patient = _patient_with_data(make_patient, assign_patient, doctor)
    client = auth_client(doctor.user)
    aid = client.post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK},
        format="json",
    ).data["assessment"]["id"]

    resp = client.post(
        f"/api/v1/risk/assessments/{aid}/review/",
        {"decision": "NEEDS_MORE_DATA", "rationale": "Repeat fasting glucose first."},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["assessment"]["lifecycle_state"] == L.REVIEW_REQUIRED
    # A second review is still possible.
    assert RiskAssessment.objects.get(public_id=aid).lifecycle_state == L.REVIEW_REQUIRED


def test_patient_cannot_review(auth_client, make_user, make_patient, enabled_task):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    assessment = RiskAssessment.objects.create(
        patient=patient, task=TASK, status=RiskAssessment.Status.COMPLETED,
        lifecycle_state=L.REVIEW_REQUIRED, outcome_code="OK", input_snapshot={},
    )
    resp = auth_client(alice).post(
        f"/api/v1/risk/assessments/{assessment.public_id}/review/",
        {"decision": "ACCEPTED", "rationale": "looks fine to me"}, format="json",
    )
    assert resp.status_code == 403


def test_review_rationale_is_required(
    auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    assessment = RiskAssessment.objects.create(
        patient=patient, task=TASK, status=RiskAssessment.Status.COMPLETED,
        lifecycle_state=L.REVIEW_REQUIRED, outcome_code="OK", input_snapshot={},
    )
    resp = auth_client(doctor.user).post(
        f"/api/v1/risk/assessments/{assessment.public_id}/review/",
        {"decision": "ACCEPTED", "rationale": ""}, format="json",
    )
    assert resp.status_code == 400
