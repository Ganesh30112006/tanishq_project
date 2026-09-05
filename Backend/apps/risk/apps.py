from __future__ import annotations

from django.apps import AppConfig


class RiskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.risk"
    label = "risk"
    verbose_name = "Risk models and assessments"
