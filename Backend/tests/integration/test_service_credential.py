"""The Django <-> intelligence boundary must fail loudly, never fall open.

Two failure modes are easy to ship and hard to notice. The service used to
carry a default token written into the repository, which is a published
credential. And an *unset* token would have made ``compare_digest("", "")``
succeed, so a deployment that simply forgot the setting would have accepted
every request that arrived with no token at all (spec section 52).
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from fastapi.testclient import TestClient

from apps.common.intelligence import IntelligenceClient
from intelligence.main import app
from intelligence.settings import IntelligenceSettings, get_settings
from intelligence import security

client = TestClient(app)


def test_no_credential_is_written_into_the_repository():
    """A default token in source is a credential everyone already has."""
    assert IntelligenceSettings().service_token == "" or "shared-secret" not in (
        IntelligenceSettings().service_token
    )


def test_an_unconfigured_service_refuses_to_serve(monkeypatch):
    """Not 200, and not 401 either - the operator has to see the cause."""
    blank = IntelligenceSettings(service_token="")
    monkeypatch.setattr(security, "get_settings", lambda: blank)

    resp = client.post(
        "/v1/infer",
        headers={"X-Correlation-Id": "c1"},
        json={
            "task": "cvd", "model_version": "1.0.0", "feature_schema_version": "fs-1",
            "features": {"glucose": 5.4}, "correlation_id": "c1",
        },
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_an_unconfigured_service_does_not_accept_an_empty_token(monkeypatch):
    """The exact hole: sending nothing must not match a configured nothing."""
    blank = IntelligenceSettings(service_token="")
    monkeypatch.setattr(security, "get_settings", lambda: blank)

    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": "", "X-Correlation-Id": "c1"},
        json={
            "task": "cvd", "model_version": "1.0.0", "feature_schema_version": "fs-1",
            "features": {"glucose": 5.4}, "correlation_id": "c1",
        },
    )
    assert resp.status_code != 200


def test_a_configured_service_still_rejects_the_wrong_token():
    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": "not-the-token", "X-Correlation-Id": "c1"},
        json={
            "task": "cvd", "model_version": "1.0.0", "feature_schema_version": "fs-1",
            "features": {"glucose": 5.4}, "correlation_id": "c1",
        },
    )
    assert resp.status_code == 401


def test_django_will_not_call_out_without_a_credential():
    """Sending an empty credential is an unauthenticated call, not a fallback."""
    with override_settings(
        INTELLIGENCE={
            "BASE_URL": "http://intelligence.invalid",
            "SERVICE_TOKEN": "",
            "TIMEOUT_SECONDS": 5,
        }
    ):
        with pytest.raises(ImproperlyConfigured):
            IntelligenceClient()


def test_django_builds_a_client_when_configured():
    with override_settings(
        INTELLIGENCE={
            "BASE_URL": "http://intelligence.invalid",
            "SERVICE_TOKEN": get_settings().service_token or "configured",
            "TIMEOUT_SECONDS": 5,
        }
    ):
        assert IntelligenceClient().token
