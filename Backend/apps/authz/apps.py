from __future__ import annotations

from django.apps import AppConfig


class AuthzConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.authz"
    label = "authz"
    verbose_name = "Resource-level authorization"

    def ready(self) -> None:
        # Register the built-in resource policies with the engine.
        from apps.authz import policies  # noqa: F401
