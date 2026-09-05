from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Accounts, roles and permissions"

    def ready(self) -> None:
        try:
            from apps.accounts import schema  # noqa: F401  (registers OpenAPI auth scheme)
        except ImportError:  # drf-spectacular optional
            pass
