"""Patients sign up and sign in with a password, so production must allow it.

``config/settings/prod.py`` used to force the password-token switch off, and
every production build answered login and sign-up with a 400. A failed
sign-up also left the account behind, so the email was taken for good.
"""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from apps.accounts.models import User
from apps.patients.models import Patient

pytestmark = pytest.mark.django_db

BACKEND = Path(__file__).resolve().parents[2]
SIGN_UP = {
    "email": "asha.rao@example.test",
    "full_name": "Asha Rao",
    "password": "a long passphrase 2026",  # noqa: S106 - test fixture
    "confirms_adult": True,
}


def _identity(**changes):
    identity = copy.deepcopy(settings.IDENTITY)
    identity.update(changes)
    return identity


def test_production_settings_leave_password_sign_in_on():
    env = {
        k: v for k, v in os.environ.items()
        if k not in {"PASSWORD_SIGN_IN", "LOCAL_DEV_TOKENS", "DJANGO_SETTINGS_MODULE"}
    }
    env.update(
        DJANGO_SECRET_KEY="prod-import-check-only",  # noqa: S106 - test fixture
        REPORT_UPLOAD_SCANNER="apps.reports.scanning:scan",
        INTELLIGENCE_SERVICE_TOKEN="prod-import-check-only",  # noqa: S106 - test fixture
        DJANGO_DB_BACKEND="sqlite",
        EMAIL_HOST="smtp.invalid",
        FRONTEND_BASE_URL="https://app.example.test",
    )
    out = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-c",
         "from config.settings import prod; "
         "print(prod.IDENTITY['PASSWORD_SIGN_IN'], prod.CACHES['default']['BACKEND'])"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert out[0] == "True"
    # Shared counters, so rate limits hold across server workers.
    assert out[1] == "django.core.cache.backends.db.DatabaseCache"


def test_sign_up_then_sign_in_works_with_production_identity(api_client):
    with override_settings(IDENTITY=_identity(PASSWORD_SIGN_IN=True)):
        assert api_client.post("/api/v1/auth/register", SIGN_UP, format="json").status_code == 201
        resp = api_client.post(
            "/api/v1/auth/login",
            {"email": SIGN_UP["email"], "password": SIGN_UP["password"]},
            format="json",
        )
    assert resp.status_code == 201
    assert resp.data["access_token"] and resp.data["refresh_token"]


def test_failed_sign_up_leaves_no_account_behind(api_client):
    with override_settings(IDENTITY=_identity(PASSWORD_SIGN_IN=False)):
        resp = api_client.post("/api/v1/auth/register", SIGN_UP, format="json")
    assert resp.status_code == 400
    assert not User.objects.filter(email=SIGN_UP["email"]).exists()
    assert not Patient.objects.filter(given_name="Asha", family_name="Rao").exists()

    # And the person can try again once sign-in works.
    with override_settings(IDENTITY=_identity(PASSWORD_SIGN_IN=True)):
        assert api_client.post("/api/v1/auth/register", SIGN_UP, format="json").status_code == 201
