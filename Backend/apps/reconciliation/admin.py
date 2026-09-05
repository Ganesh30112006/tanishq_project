from __future__ import annotations

from django.contrib import admin

from apps.reconciliation.models import ReconciliationEvent, ReconciliationItem


class ReconciliationItemInline(admin.TabularInline):
    model = ReconciliationItem
    extra = 0


@admin.register(ReconciliationEvent)
class ReconciliationEventAdmin(admin.ModelAdmin):
    list_display = ("kind", "patient", "status", "detected_at")
    list_filter = ("kind", "status")
    inlines = [ReconciliationItemInline]
