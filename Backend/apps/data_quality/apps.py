from __future__ import annotations

from django.apps import AppConfig


class DataQualityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_quality"
    label = "data_quality"
    verbose_name = "Data quality"

    def ready(self) -> None:
        from apps.data_quality import jobs  # noqa: F401
