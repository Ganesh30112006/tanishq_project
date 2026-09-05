"""Production settings.

Deployment/infrastructure concerns are out of scope for this repository;
this module only tightens application-level security defaults.
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = False

# Fail loudly if a real secret was not provided.
if SECRET_KEY == "insecure-dev-key-override-me":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Local opaque dev tokens are never accepted in production.
IDENTITY["LOCAL_DEV_TOKENS"] = False  # noqa: F405

# A real antivirus engine is required in production. The built-in content gate
# in apps/reports/scanning.py always runs and verifies that a file is the inert
# document type it claims to be, but it recognises no malware families. Public
# file upload without an engine behind it is not a risk to accept silently, so
# this refuses to start rather than running degraded.
if not REPORT_UPLOAD_SCANNER:  # noqa: F405
    raise RuntimeError(
        "REPORT_UPLOAD_SCANNER must be set in production - a 'pkg.module:callable' "
        "that raises on a malicious file. Uploads are public input; the built-in "
        "content-type gate is a backstop, not an antivirus engine."
    )

# The intelligence service credential is required on both processes; an empty
# one must never be read as "no authentication needed".
if not INTELLIGENCE.get("SERVICE_TOKEN"):  # noqa: F405
    raise RuntimeError("INTELLIGENCE_SERVICE_TOKEN must be set in production.")

if env_bool("OTEL_ENABLED", False):
    from config.observability import configure_observability

    configure_observability()
