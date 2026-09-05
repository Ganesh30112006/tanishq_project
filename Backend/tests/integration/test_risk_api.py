from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.common.enums import ClinicalDataState, ModelLifecycleState, Role
from apps.common.intelligence import InferenceResult
from apps.laboratories.models import Laboratory, LabOrder, LabResult
from apps.notifications.models import MissingDataTask, Notification
from apps.risk.models import FeatureSchema, ModelVersion, RiskAssessment, RiskModel

pytestmark = pytest.mark.django_db

TASK = "cvd"


@pytest.fixture
def enabled_task(db):
    schema = FeatureSchema.objects.create(
        task=TASK,
        version="fs-1",
        definition={
            "required_features": [
                {"name": "age", "max_age_days": 3650},
                {"name": "glucose", "max_age_days": 90},
            ],
            "minimum_completeness": 1.0,
            "valid_domain": {},
        },
    )
    mv = ModelVersion.objects.create(
        model_id="cvd-model", name="CVD", version="1.0.0", task=TASK,
        feature_schema=schema, preprocessing_version="pp-1", calibration_version="cal-1",
        explanation_version="shap-1",
        lifecycle_state=ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW,
    )
    RiskModel.objects.create(task=TASK, active_version=mv, is_enabled=True)
    return mv


def _aged_patient(make_patient, **kw):
    patient = make_patient(**kw)
    patient.date_of_birth = dt.date(1972, 6, 1)
    patient.save(update_fields=["date_of_birth"])
    return patient


def _recent_glucose(patient, *, value="5.4", days_ago=3):
    lab = Laboratory.objects.create(name="Lab", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    return LabResult.objects.create(
        order=order,
        analyte="glucose",
        value_normalized=Decimal(value),
        unit_normalized="mmol/L",
        state=ClinicalDataState.OBSERVED,
        observed_at=timezone.now() - dt.timedelta(days=days_ago),
    )


def test_doctor_gets_calibrated_prediction_when_data_is_sufficient(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    def fake_infer(self, **kwargs):
        assert "glucose" in kwargs["features"] and "age" in kwargs["features"]
        return InferenceResult(
            raw_score=0.21, calibrated_score=0.18, calibration_version="cal-1",
            reliability_status="VALID", reliability_detail={},
            shap=[{"feature": "glucose", "contribution": 0.4}], model_echo={},
        )

    monkeypatch.setattr("apps.common.intelligence.IntelligenceClient.infer", fake_infer)

    doctor = make_doctor()
    patient = _aged_patient(make_patient)
    assign_patient(doctor, patient)
    _recent_glucose(patient)

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK}, format="json"
    )
    assert resp.status_code == 201
    assert resp.data["assessment"]["status"] == "COMPLETED"
    assert resp.data["assessment"]["calibrated_score"] == "0.180000"
    assert resp.data["assessment"]["model"] == "cvd-model:1.0.0"
    assert resp.data["assessment"]["factors"][0]["feature_name"] == "glucose"
    stored = RiskAssessment.objects.get()
    assert stored.status == RiskAssessment.Status.COMPLETED
    assert stored.feature_schema_version == "fs-1"
    assert AuditLog.objects.filter(action="risk.assessment", result="SUCCESS").exists()


def test_missing_feature_blocks_and_opens_routed_tasks(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    def must_not_call(self, **kwargs):  # pragma: no cover
        raise AssertionError("model must not be called when data is insufficient")

    monkeypatch.setattr("apps.common.intelligence.IntelligenceClient.infer", must_not_call)

    doctor = make_doctor()
    patient = _aged_patient(make_patient)  # has age, but no glucose on record
    assign_patient(doctor, patient)

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["status"] == "blocked"
    assert resp.data["outcome"] == "INSUFFICIENT_DATA"
    assert resp.data["assessment"]["status"] == "BLOCKED"
    assert resp.data["assessment"]["calibrated_score"] is None

    task = MissingDataTask.objects.get(requested_data="glucose")
    assert task.assigned_role == Role.LAB_TECHNICIAN  # glucose is lab-backed
    assert Notification.objects.filter(recipient=doctor.user, category="risk_blocked").exists()


def test_no_fabrication_when_glucose_only_available_as_not_reported(
    monkeypatch, auth_client, make_doctor, make_patient, assign_patient, enabled_task
):
    monkeypatch.setattr(
        "apps.common.intelligence.IntelligenceClient.infer",
        lambda self, **kw: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    doctor = make_doctor()
    patient = _aged_patient(make_patient)
    assign_patient(doctor, patient)
    # A row exists but it is explicitly NOT_REPORTED - it must not satisfy the feature.
    lab = Laboratory.objects.create(name="Lab", code=f"L{patient.pk}")
    order = LabOrder.objects.create(laboratory=lab, patient=patient, panel="GLUCOSE")
    LabResult.objects.create(
        order=order, analyte="glucose", value_normalized=None, unit_normalized="",
        state=ClinicalDataState.NOT_REPORTED, observed_at=timezone.now(),
    )

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["outcome"] == "INSUFFICIENT_DATA"


def test_unassigned_patient_is_not_found(auth_client, make_doctor, make_patient, enabled_task):
    doctor = make_doctor()
    other = make_patient()
    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(other.public_id), "task": TASK}, format="json"
    )
    assert resp.status_code == 404


def test_patient_may_request_analysis_of_their_own_record(
    auth_client, make_user, make_patient, enabled_task
):
    """The consumer path: a person asks what their own results indicate."""
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": TASK}, format="json"
    )
    # Whether it scores or safely blocks depends on the evidence on file; what
    # matters here is that the request itself is authorized.
    assert resp.status_code in (200, 201), resp.data


def test_patient_cannot_request_analysis_for_another_person(
    auth_client, make_user, make_patient, enabled_task
):
    alice = make_user(Role.PATIENT)
    make_patient(user=alice)
    stranger = make_patient()
    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/", {"patient_id": str(stranger.public_id), "task": TASK}, format="json"
    )
    assert resp.status_code in (403, 404)


def test_patient_reads_own_assessment_only(
    auth_client, make_user, make_patient, make_doctor, assign_patient, enabled_task
):
    alice = make_user(Role.PATIENT)
    alice_patient = make_patient(user=alice)
    RiskAssessment.objects.create(
        patient=alice_patient, task=TASK, status=RiskAssessment.Status.BLOCKED,
        outcome_code="INSUFFICIENT_DATA", input_snapshot={},
    )
    other_patient = make_patient()
    RiskAssessment.objects.create(
        patient=other_patient, task=TASK, status=RiskAssessment.Status.BLOCKED,
        outcome_code="INSUFFICIENT_DATA", input_snapshot={},
    )

    resp = auth_client(alice).get("/api/v1/risk/assessments/")
    assert resp.status_code == 200
    patient_ids = {row["patient_id"] for row in resp.data["results"]}
    assert patient_ids == {str(alice_patient.public_id)}
