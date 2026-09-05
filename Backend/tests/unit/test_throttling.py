"""Rate limiting is disabled in the suite, so assert it is wired in the real
configuration rather than silently losing the control."""
from __future__ import annotations

from apps.accounts.views import LoginView, RegisterView
from config.settings import base


def test_auth_endpoints_declare_a_throttle_scope():
    assert LoginView.throttle_scope == "auth"
    assert RegisterView.throttle_scope == "auth"


def test_production_configuration_sets_auth_and_ai_rates():
    rates = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["auth"] and rates["auth"].endswith("/min")
    assert rates["ai"] and rates["risk"]
