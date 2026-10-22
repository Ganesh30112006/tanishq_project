"""Base Django settings for the CareSense AI application backend.

Django owns identity, authorization, patient scope, business state and the
primary database. Environment-specific modules (``dev``/``test``/``prod``)
import from here and override only what differs.

Secrets are read from the environment (see spec section 40). Nothing
sensitive is hard-coded.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load a local .env if present; real environments inject variables directly.
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-override-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
ROOT_URLCONF = "config.urls"

AUTH_USER_MODEL = "accounts.User"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
]

# Order matters: foundational apps first.
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.authz",
    "apps.audit",
    "apps.dashboard",
    "apps.patients",
    "apps.doctors",
    "apps.appointments",
    "apps.laboratories",
    "apps.medical_records",
    "apps.health",
    "apps.reports",
    "apps.risk",
    "apps.alerts",
    "apps.notifications",
    "apps.reconciliation",
    "apps.data_quality",
    "apps.ai",
    "apps.jobs",
    "apps.privacy",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Browser clients live on their own origin and send a bearer token; the
    # allowlist is exact-origin and credential-less (see apps/common/cors.py).
    "apps.common.cors.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Establishes a per-request correlation id + request-scoped audit context.
    "apps.audit.middleware.RequestContextMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database (MySQL 8.x is the transactional source of truth)
# --------------------------------------------------------------------------
_db_backend = env("DJANGO_DB_BACKEND", "mysql")
if _db_backend == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "caresense-dev.sqlite3",
            # SQLite is a single-writer database and is only ever a local dev
            # convenience here (MySQL 8.x is the real transactional source of
            # truth - see the DB design note above). Django's dev server
            # handles requests concurrently: in the default rollback-journal
            # mode a writer blocks every reader for the duration of its
            # transaction, so two ordinary concurrent requests routinely
            # collide. WAL mode lets readers proceed without waiting on a
            # writer (writers still queue behind each other); the busy
            # timeout then covers that remaining writer-vs-writer wait
            # instead of failing immediately with "database is locked".
            "OPTIONS": {
                "timeout": 20,
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            },
        }
    }
else:
    _db_options: dict[str, object] = {
        "charset": "utf8mb4",
        # Enforce strict mode so the DB rejects silently-truncated clinical data.
        "sql_mode": "STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO",
        "isolation_level": "read committed",
    }
    if env("MYSQL_SSL_CA"):
        _db_options["ssl"] = {"ca": env("MYSQL_SSL_CA")}
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("MYSQL_DATABASE", "caresense"),
            "USER": env("MYSQL_USER", "caresense_app"),
            "PASSWORD": env("MYSQL_PASSWORD", ""),
            "HOST": env("MYSQL_HOST", "127.0.0.1"),
            "PORT": env("MYSQL_PORT", "3306"),
            "CONN_MAX_AGE": int(env("MYSQL_CONN_MAX_AGE", "60") or "60"),
            "OPTIONS": _db_options,
        }
    }

# --------------------------------------------------------------------------
# Password hashing / validation
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.BearerTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "apps.common.errors.drf_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": "10/min",
        "ai": "30/min",
        "risk": "60/min",
    },
    "UNAUTHENTICATED_USER": None,
}

# --------------------------------------------------------------------------
# Cross-origin access for the browser client
# --------------------------------------------------------------------------
CORS = {
    "ALLOWED_ORIGINS": env_list("CORS_ALLOWED_ORIGINS", ""),
}

# --------------------------------------------------------------------------
# Risk display bands (presentation only - NOT a clinical grade)
# --------------------------------------------------------------------------
# A calibrated probability is the model's output; a coloured band is an
# operational display convenience. The cut points are configuration, never
# hard-coded medical urgency (spec sections 27, 31, 35), and a band is only
# ever derived from a COMPLETED assessment.
# Limits on a person re-running the analysis on their own record. The model is
# deterministic: re-running unchanged inputs cannot yield a different answer,
# so a tight cooldown costs the user nothing and stops the compute being spun
# pointlessly. A *blocked* attempt is exempt from the cooldown - someone who
# was told data was missing must be able to upload it and retry at once.
SELF_SERVICE_ANALYSIS = {
    "COOLDOWN_MINUTES": int(env("SELF_ANALYSIS_COOLDOWN_MINUTES", "60") or "60"),
    "DAILY_CAP": int(env("SELF_ANALYSIS_DAILY_CAP", "5") or "5"),
}

# Shown with urgent-symptom guidance. Deployment-specific; left blank rather
# than defaulting to any one country's number.
# Shown with an elevated result so a frightened reader has a number to call.
# 112 is the all-services emergency number in India; override per deployment.
EMERGENCY_CONTACT_NUMBER = env("EMERGENCY_CONTACT_NUMBER", "112")

RISK_DISPLAY_BANDS = [
    {"code": "LOW", "max_probability": 0.25},
    {"code": "MEDIUM", "max_probability": 0.50},
    {"code": "HIGH", "max_probability": 0.75},
    {"code": "CRITICAL", "max_probability": 1.01},
]

SPECTACULAR_SETTINGS = {
    "TITLE": "CareSense AI API",
    "DESCRIPTION": "Healthcare / public-health decision-support backend.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # The client generator keys off operationId, so collisions must not be
    # resolved with arbitrary numeric suffixes.
    "ENUM_NAME_OVERRIDES": {
        "ClinicalDataStateEnum": "apps.common.enums.ClinicalDataState.choices",
        "ValidationStatusEnum": "apps.common.enums.ValidationStatus.choices",
        "ReportClassEnum": "apps.common.enums.ReportClass.choices",
        "MissingDataTaskStatusEnum": "apps.common.enums.MissingDataTaskStatus.choices",
        "MeasurementKindEnum": "apps.health.models.MeasurementKind.choices",
    },
}

# --------------------------------------------------------------------------
# Identity (OAuth 2.0 / OpenID Connect compatible)
# --------------------------------------------------------------------------
IDENTITY = {
    "OIDC_ISSUER": env("OIDC_ISSUER", ""),
    "OIDC_AUDIENCE": env("OIDC_AUDIENCE", "caresense-api"),
    "OIDC_JWKS_URL": env("OIDC_JWKS_URL", ""),
    # Local opaque dev tokens are only honoured when explicitly enabled.
    "LOCAL_DEV_TOKENS": env_bool("LOCAL_DEV_TOKENS", False),
    "ACCESS_TOKEN_TTL_SECONDS": int(env("ACCESS_TOKEN_TTL_SECONDS", "3600") or "3600"),
    # Long-lived but single-use and rotating; see accounts.models.RefreshToken.
    "REFRESH_TOKEN_TTL_SECONDS": int(env("REFRESH_TOKEN_TTL_SECONDS", "1209600") or "1209600"),
}

# --------------------------------------------------------------------------
# Django <-> FastAPI intelligence service boundary (section 52)
# --------------------------------------------------------------------------
INTELLIGENCE = {
    "BASE_URL": env("INTELLIGENCE_SERVICE_URL", "http://127.0.0.1:9001"),
    "SERVICE_TOKEN": env("INTELLIGENCE_SERVICE_TOKEN", ""),
    "TIMEOUT_SECONDS": float(env("INTELLIGENCE_SERVICE_TIMEOUT_SECONDS", "30") or "30"),
}

# How much the document-intelligence service is allowed to affect a report.
#
#   off       not called. The default, so behaviour is unchanged until someone
#             deliberately turns it on.
#   shadow    called, and what it said is recorded in the audit trail. The
#             outcome is untouched. Run this first: it produces the comparison
#             that would justify going further.
#   advisory  called, and may hold for review a report the existing pipeline
#             would have finalized. It may never do the reverse.
#
# Nothing the service returns is ever persisted as a clinical value in any
# mode. See apps/reports/second_reader.py.
DOCUMENT_INTELLIGENCE = {
    "MODE": env("DOCUMENT_INTELLIGENCE_MODE", "off") or "off",
}

# The patient-facing AI analysis of each report (apps/reports/analysis.py).
# Separate from the mode above: that governs whether the service may change a
# report's processing outcome, this governs whether the patient is shown what
# the AI read. The analysis is stored as AI output, never as a clinical value.
AI_ANALYSIS = {
    "ENABLED": env_bool("AI_ANALYSIS_ENABLED", True),
}

# --------------------------------------------------------------------------
# File uploads (untrusted; see section 39)
# --------------------------------------------------------------------------
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Report files are private. Locally they live under MEDIA_ROOT with a
# filesystem backend and are only ever served through the authorized
# ``/api/v1/reports/{id}/file`` endpoint - never at a guessable URL. In a real
# deployment set ``DJANGO_FILE_STORAGE`` to a private object-store backend
# (e.g. a private S3 bucket with no public ACL); the value is imported here so
# no code change is needed.
STORAGES = {
    "default": {
        "BACKEND": env(
            "DJANGO_FILE_STORAGE", "django.core.files.storage.FileSystemStorage"
        )
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Abstraction point for a malware/AV scan of uploaded report files. The default
# is a permissive no-op; production sets this to a callable
# "package.module:function" that raises on a bad file.
REPORT_UPLOAD_SCANNER = env("REPORT_UPLOAD_SCANNER", "")

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MiB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

REPORT_UPLOAD = {
    "MAX_BYTES": 25 * 1024 * 1024,
    "ALLOWED_CONTENT_TYPES": ["application/pdf", "image/png", "image/jpeg", "image/tiff"],
    "ALLOWED_EXTENSIONS": [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"],
}

# --------------------------------------------------------------------------
# Security headers (hardened further in prod)
# --------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
USE_X_FORWARDED_HOST = False

# --------------------------------------------------------------------------
# I18N / TZ
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Logging (structured; no sensitive medical content, see section 41)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "()": "apps.common.logging.StructuredFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "caresense": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

# --------------------------------------------------------------------------
# Observability (OpenTelemetry, optional and side-effect free if disabled)
# --------------------------------------------------------------------------
OTEL_ENABLED = env_bool("OTEL_ENABLED", False)
OTEL_SERVICE_NAME = env("OTEL_SERVICE_NAME", "caresense-django")
