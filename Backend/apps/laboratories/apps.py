from __future__ import annotations

from django.apps import AppConfig


class LaboratoriesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.laboratories"
    label = "laboratories"
    verbose_name = "Laboratories and lab workflow"
