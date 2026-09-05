from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.enums import ReportClass, ReportProcessingState, Role
from apps.jobs.models import Job
from apps.jobs.runner import run_once

pytestmark = pytest.mark.django_db

GLUCOSE_OK = (
    "CHEMISTRY\nCollected: 2024-05-01 09:00\nReported: 2024-05-01 15:00\nGlucose: 5.4 mmol/L\n"
)


def _pdf(name="r.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")


def test_patient_uploads_own_report_then_worker_finalizes_it(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    client = auth_client(alice)

    resp = client.post(
        "/api/v1/reports/",
        {"patient_id": str(patient.public_id), "file": _pdf(), "class_hint": ReportClass.GLUCOSE,
         "extracted_text": GLUCOSE_OK},
        format="multipart",
    )
    assert resp.status_code == 201
    report_id = resp.data["id"]
    assert resp.data["processing_state"] == ReportProcessingState.RECEIVED

    assert Job.objects.filter(job_type="reports.process").exists()
    run_once(worker_id="test")

    detail = client.get(f"/api/v1/reports/{report_id}/")
    assert detail.status_code == 200
    assert detail.data["processing_state"] == ReportProcessingState.FINALIZED
    assert detail.data["tests"][0]["name"] == "glucose"
    assert float(detail.data["tests"][0]["value_normalized"]) == 5.4

    quality = client.get(f"/api/v1/reports/{report_id}/quality/")
    assert quality.status_code == 200
    assert quality.data["completeness"] == "COMPLETE"
    assert quality.data["required_fields_missing"] == 0
    assert "not a medical health score" in quality.data["note"]


def test_patient_cannot_upload_for_another_patient(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    make_patient(user=alice)
    victim = make_patient()

    resp = auth_client(alice).post(
        "/api/v1/reports/",
        {"patient_id": str(victim.public_id), "file": _pdf(), "extracted_text": GLUCOSE_OK},
        format="multipart",
    )
    assert resp.status_code == 404


def test_doctor_has_no_upload_permission(auth_client, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)

    resp = auth_client(doctor.user).post(
        "/api/v1/reports/",
        {"patient_id": str(patient.public_id), "file": _pdf(), "extracted_text": GLUCOSE_OK},
        format="multipart",
    )
    assert resp.status_code == 403
    assert resp.data["error"]["code"] == "ACCESS_DENIED"


def test_disallowed_file_type_is_rejected(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    bad = SimpleUploadedFile("evil.exe", b"MZ", content_type="application/x-msdownload")

    resp = auth_client(alice).post(
        "/api/v1/reports/",
        {"patient_id": str(patient.public_id), "file": bad},
        format="multipart",
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "VALIDATION_FAILED"
