from __future__ import annotations

from django.contrib import admin

from apps.alerts.models import Alert


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("title", "patient", "severity", "status", "created_at")
    list_filter = ("severity", "status", "category")
