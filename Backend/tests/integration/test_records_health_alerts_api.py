from __future__ import annotations

import pytest
from django.utils import timezone

from apps.alerts.models import Alert
from apps.common.enums import ClinicalDataState, Role
from apps.medical_records.models import ClinicalNote, Condition

pytestmark = pytest.mark.django_db


def test_doctor_creates_condition_for_assigned_patient(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    client = auth_client(doctor.user)

    resp = client.post(
        "/api/v1/records/conditions/",
        {"patient_id": str(patient.public_id), "label": "Type 2 diabetes", "clinical_status": "ACTIVE"},
        format="json",
    )
    assert resp.status_code == 201
    assert Condition.objects.filter(patient=patient, label="Type 2 diabetes").exists()


def test_doctor_cannot_write_to_unassigned_patient(auth_client, make_doctor, make_patient):
    doctor = make_doctor()
    other = make_patient()
    resp = auth_client(doctor.user).post(
        "/api/v1/records/conditions/",
        {"patient_id": str(other.public_id), "label": "X"},
        format="json",
    )
    assert resp.status_code == 404


def test_clinical_note_is_append_only_with_addendum(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    client = auth_client(doctor.user)

    r1 = client.post(
        "/api/v1/records/notes/",
        {"patient_id": str(patient.public_id), "body": "Initial assessment."},
        format="json",
    )
    assert r1.status_code == 201
    note_id = r1.data["id"]

    r2 = client.post(
        "/api/v1/records/notes/",
        {"patient_id": str(patient.public_id), "body": "Correction.", "amends_id": note_id},
        format="json",
    )
    assert r2.status_code == 201
    assert r2.data["note_type"] == "ADDENDUM"
    assert ClinicalNote.objects.filter(patient=patient).count() == 2


def test_health_measurement_rejects_fabrication(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    client = auth_client(doctor.user)

    # A value with a non-observed state must be refused.
    resp = client.post(
        "/api/v1/health/measurements/",
        {
            "patient_id": str(patient.public_id), "kind": "HEART_RATE",
            "state": ClinicalDataState.NOT_REPORTED, "value": "72",
            "observed_at": timezone.now().isoformat(),
        },
        format="json",
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "VALIDATION_FAILED"


def test_alert_lifecycle(auth_client, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    client = auth_client(doctor.user)

    resp = client.post(
        "/api/v1/alerts/",
        {"patient_id": str(patient.public_id), "category": "followup", "title": "Recheck labs",
         "severity": "MEDIUM"},
        format="json",
    )
    assert resp.status_code == 201
    alert_id = resp.data["id"]

    assert client.post(f"/api/v1/alerts/{alert_id}/acknowledge/").data["status"] == "ACKNOWLEDGED"
    assert client.post(f"/api/v1/alerts/{alert_id}/resolve/").data["status"] == "RESOLVED"
    assert Alert.objects.get(public_id=alert_id).status == "RESOLVED"


def test_patient_reads_own_conditions(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    Condition.objects.create(patient=patient, label="Asthma", clinical_status="ACTIVE")
    other = make_patient()
    Condition.objects.create(patient=other, label="Other", clinical_status="ACTIVE")

    resp = auth_client(alice).get("/api/v1/records/conditions/")
    assert resp.status_code == 200
    labels = {row["label"] for row in resp.data["results"]}
    assert labels == {"Asthma"}
