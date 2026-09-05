from __future__ import annotations

from django.contrib import admin

from apps.notifications.models import MissingDataTask, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("subject", "recipient", "category", "status", "created_at")
    list_filter = ("status", "category", "channel")


@admin.register(MissingDataTask)
class MissingDataTaskAdmin(admin.ModelAdmin):
    list_display = ("requested_data", "patient", "assigned_role", "status", "lookup_state", "due_at")
    list_filter = ("assigned_role", "status", "lookup_state", "source_workflow")
