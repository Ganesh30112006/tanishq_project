from __future__ import annotations

import pytest

from apps.accounts.models import AccessToken
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def test_login_returns_token_and_me_reports_permissions(api_client, make_user):
    from apps.common.enums import Role

    make_user(Role.DOCTOR, email="doc@example.test", password="a strong passphrase 1")

    resp = api_client.post(
        "/api/v1/auth/login",
        {"email": "doc@example.test", "password": "a strong passphrase 1"},
        format="json",
    )
    assert resp.status_code == 201
    token = resp.data["access_token"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    me = api_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert "risk.request" in me.data["permissions"]
    assert AuditLog.objects.filter(action="auth.login", result="SUCCESS").exists()


def test_bad_password_is_rejected_and_audited(api_client, make_user):
    make_user(email="x@example.test", password="the right passphrase")
    resp = api_client.post(
        "/api/v1/auth/login",
        {"email": "x@example.test", "password": "wrong"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.data["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert AuditLog.objects.filter(action="auth.login.failed", result="DENIED").exists()


def test_revoked_token_is_refused(api_client, make_user):
    from apps.accounts.services import AccountService

    user = make_user()
    raw = AccountService().issue_local_token(user).raw
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert api_client.get("/api/v1/auth/me").status_code == 200

    AccountService().revoke_token(raw)
    resp = api_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert AccessToken.objects.get(user=user).revoked_at is not None


def test_error_envelope_has_no_internal_details(api_client):
    resp = api_client.get("/api/v1/patients/")
    assert resp.status_code == 401
    body = resp.data["error"]
    assert set(body) == {"code", "message", "details", "request_id"}
