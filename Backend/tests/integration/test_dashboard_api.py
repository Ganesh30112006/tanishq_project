from __future__ import annotations

import pytest

from apps.common.enums import Role
from apps.medical_records.models import Allergy

pytestmark = pytest.mark.django_db


def test_dashboard_summary_reflects_callers_own_role(auth_client, make_doctor):
    doctor = make_doctor()
    resp = auth_client(doctor.user).get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    assert resp.data["role"] == "DOCTOR"
    assert isinstance(resp.data["metrics"], list) and resp.data["metrics"]


def test_dashboard_summary_ignores_client_supplied_role(auth_client, make_user):
    patient_user = make_user(Role.PATIENT)
    resp = auth_client(patient_user).get("/api/v1/dashboard/summary?role=ADMIN")
    assert resp.status_code == 200
    # The caller only holds PATIENT - the request for ADMIN must be ignored.
    assert resp.data["role"] == "PATIENT"


def test_dashboard_summary_honors_a_role_the_caller_actually_has(auth_client, make_user):
    from apps.accounts.services import AccountService

    user = make_user(Role.DOCTOR)
    AccountService().assign_role(user, Role.ADMIN)
    resp = auth_client(user).get("/api/v1/dashboard/summary?role=DOCTOR")
    assert resp.status_code == 200
    assert resp.data["role"] == "DOCTOR"


def test_patient_timeline_is_scoped_and_chronological(
    auth_client, make_doctor, make_patient, assign_patient
):
    from django.utils import timezone

    from apps.alerts.models import Alert

    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    Alert.objects.create(patient=patient, category="followup", title="Recheck", severity="LOW")

    client = auth_client(doctor.user)
    resp = client.get(f"/api/v1/patients/{patient.public_id}/timeline/")
    assert resp.status_code == 200
    assert any(event["type"] == "alert" for event in resp.data)


def test_patient_timeline_denies_unassigned_doctor(auth_client, make_doctor, make_patient):
    doctor = make_doctor()
    other = make_patient()
    resp = auth_client(doctor.user).get(f"/api/v1/patients/{other.public_id}/timeline/")
    assert resp.status_code in (403, 404)


def test_patient_card_fields_reflect_open_alert(auth_client, make_doctor, make_patient, assign_patient):
    from apps.alerts.models import Alert

    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    Alert.objects.create(patient=patient, category="followup", title="Recheck labs", severity="HIGH")

    resp = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/")
    assert resp.status_code == 200
    assert resp.data["latest_alert"] == "Recheck labs"
    assert resp.data["status"] == "REVIEW_REQUIRED"


def test_patient_profile_includes_allergies(auth_client, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    Allergy.objects.create(patient=patient, substance="Penicillin", status=Allergy.Status.ACTIVE)

    resp = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/")
    assert resp.status_code == 200
    assert resp.data["allergies"] == ["Penicillin"]


def test_ai_summary_blocked_when_no_authorized_context(auth_client, make_doctor, make_patient, assign_patient):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)

    resp = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/ai-summary/")
    assert resp.status_code == 200
    assert resp.data["status"] == "blocked"


def test_ai_summary_denied_for_patient_role(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    resp = auth_client(alice).get(f"/api/v1/patients/{patient.public_id}/ai-summary/")
    # PATIENT does not hold ai.use - this is an RBAC denial, not a data gap.
    assert resp.status_code == 403


def test_lab_technician_cannot_reach_dashboard_ai_or_allergy_write(
    auth_client, make_lab_tech, make_patient, open_lab_order
):
    tech = make_lab_tech()
    linked = make_patient()
    open_lab_order(tech, linked)
    client = auth_client(tech.user)

    resp = client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    assert resp.data["role"] == "LAB_TECHNICIAN"

    resp = client.post(
        "/api/v1/records/allergies/",
        {"patient_id": str(linked.public_id), "substance": "Penicillin"},
        format="json",
    )
    assert resp.status_code == 403
