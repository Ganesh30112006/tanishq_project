"""Production settings.

Deployment/infrastructure concerns are out of scope for this repository;
this module only tightens application-level security defaults.
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = False

# Fail loudly if a real secret was not provided.
if SECRET_KEY == "insecure-dev-key-override-me":  # noqa: F405,S105 - the value being refused
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production.")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Rate-limit counters must be shared. The default in-process cache gives each
# server worker its own count, so four workers allow four times the login
# attempts. The database is already shared, so it needs no new service.
# Create the table once per database with: manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "caresense_cache",
    }
}

# Password sign-in is NOT forced off here. It is the product's only way in -
# patients self-register - and forcing it off made login and sign-up return 400
# on every production build. Set PASSWORD_SIGN_IN=false only once an external
# IdP issues every token.

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

# Password reset is the only way back into a forgotten account; there is no
# staff member to call. It needs a mail server and the app's public address.
if not EMAIL_HOST:  # noqa: F405
    raise RuntimeError("EMAIL_HOST must be set in production - password reset sends email.")
if not FRONTEND_BASE_URL.startswith("https://"):  # noqa: F405
    raise RuntimeError(
        "FRONTEND_BASE_URL must be the app's https:// address in production - "
        "password-reset links point at it."
    )

# The Django admin site and the API explorer are not part of the product (the
# app has its own admin area) and are a login form and a full API map exposed
# to the internet. Off unless a deployment deliberately turns them on.
EXPOSE_DJANGO_ADMIN = env_bool("DJANGO_EXPOSE_ADMIN", False)
EXPOSE_API_DOCS = env_bool("DJANGO_EXPOSE_API_DOCS", False)

if env_bool("OTEL_ENABLED", False):
    from config.observability import configure_observability

    configure_observability()
