"""Rate limiting is disabled in the suite, so assert it is wired in the real
configuration rather than silently losing the control."""
from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.throttling import LoginAccountThrottle
from apps.accounts.views import LoginView, RegisterView
from config.settings import base

LIVE_RATES = {"auth": "10/min", "auth_account": "20/hour", "ai": "30/min", "risk": "60/min"}


def test_auth_endpoints_declare_a_throttle_scope():
    assert LoginView.throttle_scope == "auth"
    assert RegisterView.throttle_scope == "auth"
    assert LoginAccountThrottle in LoginView.throttle_classes


def test_production_configuration_sets_auth_and_ai_rates():
    rates = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["auth"] and rates["auth"].endswith("/min")
    assert rates["auth_account"]
    assert rates["ai"] and rates["risk"]


def test_forwarded_header_is_not_trusted_unless_proxies_are_declared():
    assert base.REST_FRAMEWORK["NUM_PROXIES"] == 0


@pytest.fixture
def live_rates(monkeypatch, settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", LIVE_RATES)
    monkeypatch.setattr(LoginAccountThrottle, "THROTTLE_RATES", LIVE_RATES)
    cache.clear()
    yield
    cache.clear()


def _login(client, email="x@example.test", **extra):
    return client.post(
        "/api/v1/auth/login", {"email": email, "password": "wrong-password-1"},
        format="json", **extra,
    ).status_code


@pytest.mark.django_db
def test_a_new_forwarded_header_per_request_does_not_reset_the_login_limit(live_rates):
    client = APIClient()
    codes = [_login(client, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}") for i in range(12)]
    assert codes.count(429) >= 1


@pytest.mark.django_db
def test_one_account_is_limited_across_client_addresses(live_rates):
    client = APIClient()
    codes = [
        _login(client, email=" Victim@Example.test ", REMOTE_ADDR=f"10.1.{i // 250}.{i % 250}")
        for i in range(21)
    ]
    assert codes[:20].count(429) == 0
    assert codes[20] == 429
