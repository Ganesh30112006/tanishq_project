"""CI settings: run the test suite against a real MySQL 8 server.

The default ``test`` settings use in-memory SQLite for speed; this module
points the same suite at MySQL so migrations, constraints, ``SELECT ... FOR
UPDATE SKIP LOCKED`` and strict-mode behaviour are exercised for real. The
``MYSQL_*`` variables are supplied by the CI job.
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_DB_BACKEND", "mysql")
os.environ.setdefault("DJANGO_SECRET_KEY", "ci-secret-key")
os.environ.setdefault("LOCAL_DEV_TOKENS", "true")
os.environ.setdefault("INTELLIGENCE_SERVICE_TOKEN", "ci-service-token")

from .base import *  # noqa: E402,F401,F403
from .base import IDENTITY  # noqa: E402

DEBUG = False
TESTING = True
IDENTITY["LOCAL_DEV_TOKENS"] = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
INTELLIGENCE["BASE_URL"] = "http://intelligence.invalid"  # noqa: F405
