"""The consumer path: sign up, get a record, ask what your results mean."""
from __future__ import annotations

import uuid

import pytest

from apps.accounts.models import User
from apps.common.enums import Role
from apps.patients.models import Patient
from apps.risk.models import RiskAssessment

pytestmark = pytest.mark.django_db


def _register(api_client, **overrides):
    payload = {
        "email": f"self-{uuid.uuid4().hex[:8]}@example.test",
        "full_name": "Alex Morgan",
        "password": "a-long-enough-passphrase",
        "date_of_birth": "1980-05-04",
        "sex": "FEMALE",
    }
    payload.update(overrides)
    return api_client.post("/api/v1/auth/register", payload, format="json")


def test_sign_up_creates_the_persons_own_record(api_client):
    resp = _register(api_client)
    assert resp.status_code == 201, resp.data

    user = User.objects.get(email__startswith="self-")
    patient = Patient.objects.get(user=user)
    assert patient.mrn.startswith("CS-")
    assert patient.given_name == "Alex"
    assert str(patient.date_of_birth) == "1980-05-04"
    assert user.has_role(Role.PATIENT)


def test_new_account_sees_its_own_record_immediately(api_client, auth_client):
    _register(api_client)
    user = User.objects.get(email__startswith="self-")
    patient = Patient.objects.get(user=user)

    listing = auth_client(user).get("/api/v1/patients/")
    ids = [row["id"] for row in listing.data["results"]]
    assert ids == [str(patient.public_id)]
    assert auth_client(user).get(f"/api/v1/patients/{patient.public_id}/").status_code == 200


def test_sign_up_never_attaches_to_an_existing_record(api_client, make_patient):
    existing = make_patient(mrn="MRN-EXISTING-1")
    _register(api_client, full_name=existing.full_name)
    existing.refresh_from_db()
    assert existing.user is None


def test_two_sign_ups_get_distinct_records(api_client):
    assert _register(api_client).status_code == 201
    assert _register(api_client).status_code == 201
    numbers = set(Patient.objects.values_list("mrn", flat=True))
    assert len(numbers) == 2


def test_patient_can_request_analysis_of_their_own_record(api_client, auth_client):
    _register(api_client)
    user = User.objects.get(email__startswith="self-")
    patient = Patient.objects.get(user=user)

    resp = auth_client(user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    # No model is registered in the test database, so the safe outcome is a
    # structured block - never a fabricated score.
    assert resp.status_code == 200, resp.data
    assert resp.data["status"] == "blocked"
    assert resp.data["assessment"]["calibrated_score"] is None
    stored = RiskAssessment.objects.get(patient=patient)
    assert stored.status == RiskAssessment.Status.BLOCKED


def test_patient_cannot_request_analysis_for_someone_else(api_client, auth_client, make_patient):
    _register(api_client)
    user = User.objects.get(email__startswith="self-")
    stranger = make_patient(mrn="MRN-STRANGER-1")

    resp = auth_client(user).post(
        "/api/v1/risk/assessments/", {"patient_id": str(stranger.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code in (403, 404)
    assert not RiskAssessment.objects.filter(patient=stranger).exists()
