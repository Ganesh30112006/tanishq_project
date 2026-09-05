"""Local development settings.

Defaults to SQLite so the project runs without a MySQL server. Set
``DJANGO_DB_BACKEND=mysql`` (and the ``MYSQL_*`` variables) to exercise the
real database locally.
"""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_DB_BACKEND", "sqlite")
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("LOCAL_DEV_TOKENS", "true")

from .base import *  # noqa: E402,F401,F403
from .base import IDENTITY  # noqa: E402

DEBUG = True
IDENTITY["LOCAL_DEV_TOKENS"] = True

# Console email + relaxed cookie flags for plain-HTTP local work only.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
