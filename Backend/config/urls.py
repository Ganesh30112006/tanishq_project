"""Root URL configuration.

All application endpoints live under ``/api/v1/`` (spec section 42). Each app
owns its own router; this module only mounts them.
"""
from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def healthz(_request) -> JsonResponse:
    """Liveness: is this process serving? Deliberately does not touch anything else."""
    return JsonResponse({"status": "ok", "service": "caresense-django"})


def readyz(_request) -> JsonResponse:
    """Readiness: is the *system* actually able to do its work?

    Separate from ``healthz`` on purpose. A web process can serve HTTP perfectly
    while the database is unreachable or the job worker is dead, and in this
    system a dead worker is invisible from the outside - uploads still return
    201 and then never finish. This is the endpoint monitoring should watch.

    Unauthenticated, and it returns only counts and states: no patient data, no
    identifiers, nothing that would be worth reading if it were exposed.
    """
    from django.db import connection

    from apps.jobs.health import queue_status

    checks: dict[str, object] = {}
    ok = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - report, never leak the connection string
        checks["database"] = {"status": "down", "detail": type(exc).__name__}
        ok = False

    try:
        jobs = queue_status()
        checks["jobs"] = jobs
        if jobs["status"] == "down":
            ok = False
    except Exception as exc:  # noqa: BLE001
        checks["jobs"] = {"status": "unknown", "detail": type(exc).__name__}
        ok = False

    return JsonResponse(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status=200 if ok else 503,
    )


api_v1 = [
    path("auth/", include("apps.accounts.urls")),
    path("users/", include("apps.accounts.admin_urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("patients/", include("apps.patients.urls")),
    path("doctors/", include("apps.doctors.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("labs/", include("apps.laboratories.urls")),
    path("records/", include("apps.medical_records.urls")),
    path("health/", include("apps.health.urls")),
    path("reports/", include("apps.reports.urls")),
    path("risk/", include("apps.risk.urls")),
    path("alerts/", include("apps.alerts.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("reconciliation/", include("apps.reconciliation.urls")),
    path("ai/", include("apps.ai.urls")),
    path("audit/", include("apps.audit.urls")),
]

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "api-v1"))),
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
