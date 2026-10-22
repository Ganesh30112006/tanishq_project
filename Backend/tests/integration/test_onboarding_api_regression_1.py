"""Date of birth must be a date a living person could have been born on.

The age derived from it is an input to the AI analysis, so an impossible one
must be refused at the door rather than stored and passed along.
"""
# Regression: ISSUE-001 — sign-up accepted a date of birth in the future or in 1800
# Found by /qa on 2026-10-22
# Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db


def _register(api_client, date_of_birth: str):
    email = f"dob-{uuid.uuid4().hex[:8]}@example.test"
    resp = api_client.post(
        "/api/v1/auth/register",
        {
            "email": email,
            "full_name": "Dob Check",
            "password": "a-long-enough-passphrase",
            "date_of_birth": date_of_birth,
        },
        format="json",
    )
    return resp, email


@pytest.mark.parametrize(
    "date_of_birth",
    [
        (timezone.localdate() + dt.timedelta(days=1)).isoformat(),
        "2099-01-01",
        "1800-01-01",
    ],
)
def test_self_registration_refuses_an_impossible_date_of_birth(api_client, date_of_birth):
    resp, email = _register(api_client, date_of_birth)
    assert resp.status_code == 400
    assert "date_of_birth" in resp.data["error"]["details"]["fields"]
    assert not User.objects.filter(email=email).exists()


def test_self_registration_accepts_a_birth_today(api_client):
    resp, email = _register(api_client, timezone.localdate().isoformat())
    assert resp.status_code == 201, resp.data
    assert Patient.objects.get(user__email=email).date_of_birth == timezone.localdate()


def test_staff_registration_refuses_a_future_date_of_birth(auth_client, make_doctor):
    client = auth_client(make_doctor().user)
    resp = client.post(
        "/api/v1/patients/",
        {"mrn": "MRN-DOB-1", "given_name": "Not", "family_name": "Yet", "date_of_birth": "2099-01-01"},
        format="json",
    )
    assert resp.status_code == 400
    assert not Patient.objects.filter(mrn="MRN-DOB-1").exists()
