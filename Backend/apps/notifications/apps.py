from __future__ import annotations

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications and missing-data tasks"

    def ready(self) -> None:
        from apps.notifications import jobs  # noqa: F401
