"""ISSUE-007 regression: no reassurance on a record nobody has checked.

A new account with no risk estimate and no alert was told its record was
"Stable". Nothing had been judged, so the Overview says so instead.
"""
from __future__ import annotations

import pytest

from apps.common.enums import Role

pytestmark = pytest.mark.django_db


def test_new_record_is_not_called_stable(make_user, make_patient, auth_client):
    user = make_user(Role.PATIENT)
    make_patient(user=user)

    resp = auth_client(user).get("/api/v1/dashboard/summary")

    assert resp.status_code == 200
    status = next(m for m in resp.data["metrics"] if m["label"] == "Record status")
    assert status["value"] == "Not checked yet"
    assert status["tone"] == "neutral"
