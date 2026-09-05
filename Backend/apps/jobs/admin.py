from __future__ import annotations

from django.contrib import admin

from apps.jobs.models import Job


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("job_type", "state", "attempts", "max_attempts", "available_at", "finished_at")
    list_filter = ("state", "job_type")
    search_fields = ("correlation_id", "idempotency_key")
    readonly_fields = ("public_id", "created_at", "updated_at")
