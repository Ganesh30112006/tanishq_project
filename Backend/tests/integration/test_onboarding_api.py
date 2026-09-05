"""Onboarding: self-registration, patient registration and staff access grants.

These endpoints hand out access, so the denial paths are asserted as firmly as
the happy paths (spec sections 41, 53).
"""
from __future__ import annotations

import uuid

import pytest

from apps.accounts.models import User
from apps.common.enums import Role
from apps.doctors.models import Doctor, DoctorPatientAssignment
from apps.laboratories.models import Laboratory, LabTechnician
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def _email() -> str:
    return f"new-{uuid.uuid4().hex[:8]}@example.test"


# --- public self-registration -----------------------------------------
def test_self_registration_creates_the_persons_own_record(api_client):
    email = _email()
    resp = api_client.post(
        "/api/v1/auth/register",
        {"email": email, "full_name": "Sam Patient", "password": "a-long-enough-passphrase"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["access_token"]

    user = User.objects.get(email=email)
    assert user.has_role(Role.PATIENT)
    # Self-service: the account gets a fresh record of its own, keyed to this
    # user. It is never resolved from an existing record (see the next test).
    own = Patient.objects.get(user=user)
    assert own.mrn.startswith("CS-")


def test_self_registration_cannot_claim_an_existing_patients_record(api_client, make_patient):
    existing = make_patient(mrn="MRN-TARGET-1")
    resp = api_client.post(
        "/api/v1/auth/register",
        {
            "email": _email(),
            "full_name": existing.full_name,
            "password": "a-long-enough-passphrase",
        },
        format="json",
    )
    assert resp.status_code == 201
    existing.refresh_from_db()
    assert existing.user is None


def test_duplicate_registration_does_not_confirm_the_address(api_client, make_user):
    user = make_user(Role.PATIENT)
    resp = api_client.post(
        "/api/v1/auth/register",
        {"email": user.email, "full_name": "Someone Else", "password": "a-long-enough-passphrase"},
        format="json",
    )
    assert resp.status_code == 400
    assert "already registered" not in resp.data["error"]["message"].lower()


def test_self_registration_rejects_a_weak_password(api_client):
    resp = api_client.post(
        "/api/v1/auth/register",
        {"email": _email(), "full_name": "Weak", "password": "short"},
        format="json",
    )
    assert resp.status_code == 400


# --- staff patient registration ---------------------------------------
def test_doctor_registers_patient_and_is_auto_assigned(auth_client, make_doctor):
    doctor = make_doctor()
    client = auth_client(doctor.user)
    resp = client.post(
        "/api/v1/patients/",
        {"mrn": "MRN-NEW-001", "given_name": "Ada", "family_name": "Lovelace", "sex": "FEMALE"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    patient = Patient.objects.get(mrn="MRN-NEW-001")
    # The registering clinician gets access, otherwise the record is orphaned.
    assert DoctorPatientAssignment.objects.filter(
        doctor=doctor, patient=patient, status=DoctorPatientAssignment.Status.ACTIVE
    ).exists()
    assert client.get(f"/api/v1/patients/{patient.public_id}/").status_code == 200


def test_patient_role_cannot_register_a_patient(auth_client, make_user):
    client = auth_client(make_user(Role.PATIENT))
    resp = client.post(
        "/api/v1/patients/",
        {"mrn": "MRN-NEW-002", "given_name": "No", "family_name": "Way"},
        format="json",
    )
    assert resp.status_code == 403
    assert not Patient.objects.filter(mrn="MRN-NEW-002").exists()


def test_duplicate_mrn_is_rejected(auth_client, make_doctor, make_patient):
    make_patient(mrn="MRN-DUP-1")
    client = auth_client(make_doctor().user)
    resp = client.post(
        "/api/v1/patients/",
        {"mrn": "MRN-DUP-1", "given_name": "Dup", "family_name": "Licate"},
        format="json",
    )
    assert resp.status_code == 400


# --- linking a login to a record --------------------------------------
def test_admin_links_account_and_patient_then_sees_own_record(
    auth_client, make_user, make_patient
):
    admin = make_user(Role.ADMIN)
    patient_user = make_user(Role.PATIENT)
    patient = make_patient(mrn="MRN-LINK-1")

    resp = auth_client(admin).post(
        f"/api/v1/patients/{patient.public_id}/link-account/",
        {"user_email": patient_user.email},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    patient.refresh_from_db()
    assert patient.user_id == patient_user.pk
    linked = auth_client(patient_user).get(f"/api/v1/patients/{patient.public_id}/")
    assert linked.status_code == 200


def test_non_admin_cannot_link_an_account(auth_client, make_doctor, make_user, make_patient):
    doctor = make_doctor()
    patient = make_patient(mrn="MRN-LINK-2")
    resp = auth_client(doctor.user).post(
        f"/api/v1/patients/{patient.public_id}/link-account/",
        {"user_email": make_user(Role.PATIENT).email},
        format="json",
    )
    assert resp.status_code in (403, 404)
    patient.refresh_from_db()
    assert patient.user is None


def test_cannot_link_an_account_already_bound_to_another_record(
    auth_client, make_user, make_patient
):
    admin = make_user(Role.ADMIN)
    patient_user = make_user(Role.PATIENT)
    make_patient(user=patient_user, mrn="MRN-BOUND-1")
    other = make_patient(mrn="MRN-BOUND-2")

    resp = auth_client(admin).post(
        f"/api/v1/patients/{other.public_id}/link-account/",
        {"user_email": patient_user.email},
        format="json",
    )
    assert resp.status_code == 400
    other.refresh_from_db()
    assert other.user is None


# --- staff onboarding --------------------------------------------------
def test_admin_creates_doctor_profile_and_assigns_patient(auth_client, make_user, make_patient):
    admin = make_user(Role.ADMIN)
    client = auth_client(admin)
    doctor_user = make_user(Role.DOCTOR)
    patient = make_patient(mrn="MRN-STAFF-1")

    created = client.post(
        "/api/v1/doctors/profiles/",
        {
            "user_email": doctor_user.email,
            "registration_number": "GMC-99887",
            "specialty": "Cardiology",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    doctor = Doctor.objects.get(user=doctor_user)

    # Before assignment the clinician cannot reach the record.
    before = auth_client(doctor_user).get(f"/api/v1/patients/{patient.public_id}/")
    assert before.status_code in (403, 404)

    granted = client.post(
        "/api/v1/doctors/admin/assignments/",
        {
            "doctor_id": str(doctor.public_id),
            "patient_id": str(patient.public_id),
            "reason": "Referral",
        },
        format="json",
    )
    assert granted.status_code == 201, granted.data
    after = auth_client(doctor_user).get(f"/api/v1/patients/{patient.public_id}/")
    assert after.status_code == 200

    # Ending the assignment revokes that access again.
    ended = client.post(
        f"/api/v1/doctors/admin/assignments/{granted.data['id']}/end/",
        {"reason": "Discharged"},
        format="json",
    )
    assert ended.status_code == 200
    revoked = auth_client(doctor_user).get(f"/api/v1/patients/{patient.public_id}/")
    assert revoked.status_code in (403, 404)


def test_doctor_profile_requires_the_doctor_role(auth_client, make_user):
    client = auth_client(make_user(Role.ADMIN))
    resp = client.post(
        "/api/v1/doctors/profiles/",
        {"user_email": make_user(Role.PATIENT).email, "registration_number": "GMC-11111"},
        format="json",
    )
    assert resp.status_code == 400


def test_doctor_cannot_grant_themselves_a_patient(auth_client, make_doctor, make_patient):
    doctor = make_doctor()
    patient = make_patient(mrn="MRN-SELF-1")
    resp = auth_client(doctor.user).post(
        "/api/v1/doctors/admin/assignments/",
        {"doctor_id": str(doctor.public_id), "patient_id": str(patient.public_id)},
        format="json",
    )
    assert resp.status_code == 403
    assert not DoctorPatientAssignment.objects.filter(doctor=doctor, patient=patient).exists()


def test_admin_onboards_lab_technician_to_a_laboratory(auth_client, make_user):
    client = auth_client(make_user(Role.ADMIN))
    tech_user = make_user(Role.LAB_TECHNICIAN)

    lab = client.post(
        "/api/v1/labs/laboratories/",
        {"code": "lab-north", "name": "North Laboratory"},
        format="json",
    )
    assert lab.status_code == 201, lab.data
    assert lab.data["code"] == "LAB-NORTH"

    tech = client.post(
        "/api/v1/labs/technicians/",
        {"user_email": tech_user.email, "laboratory_id": lab.data["id"], "employee_id": "T-1"},
        format="json",
    )
    assert tech.status_code == 201, tech.data
    assert LabTechnician.objects.filter(user=tech_user, laboratory__code="LAB-NORTH").exists()


def test_lab_technician_cannot_onboard_staff(auth_client, make_lab_tech):
    client = auth_client(make_lab_tech().user)
    assert client.get("/api/v1/labs/technicians/").status_code == 403
    rogue = client.post(
        "/api/v1/labs/laboratories/", {"code": "X", "name": "Rogue"}, format="json"
    )
    assert rogue.status_code == 403
    assert not Laboratory.objects.filter(code="X").exists()
