from __future__ import annotations

from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    label = "reports"
    verbose_name = "Reports and report intelligence"

    def ready(self) -> None:
        # Register background job handlers (spec section 47).
        from apps.reports import jobs  # noqa: F401
