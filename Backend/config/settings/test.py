"""Test settings.

The primary deployment target is MySQL 8.x, but the automated suite runs
against in-memory SQLite so it needs no external database. Migrations are
authored to stay MySQL-compatible; a CI job should additionally run the
suite against a real MySQL instance.
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_DB_BACKEND", "sqlite")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOCAL_DEV_TOKENS", "true")
os.environ.setdefault("INTELLIGENCE_SERVICE_TOKEN", "test-service-token")

from .base import *  # noqa: E402,F401,F403
from .base import IDENTITY  # noqa: E402

DEBUG = False
TESTING = True

DATABASES = {
    "default": {
            "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

IDENTITY["LOCAL_DEV_TOKENS"] = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Keep the intelligence client from making real network calls in tests.
INTELLIGENCE["BASE_URL"] = "http://intelligence.invalid"  # noqa: F405

# Rate limiting is a real control (see base.py), but its counters are process
# global, so leaving it on makes tests depend on execution order. The suite
# asserts the *configuration* instead; see tests/unit/test_throttling.py.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {"auth": None, "ai": None, "risk": None},
}

# The second reader is OFF for the suite regardless of what the developer has
# in their .env. A test run that silently inherited `shadow` or `advisory`
# would be exercising a different system from the one the assertions describe,
# and the tests that need a mode set it themselves.
DOCUMENT_INTELLIGENCE = {"MODE": "off"}
