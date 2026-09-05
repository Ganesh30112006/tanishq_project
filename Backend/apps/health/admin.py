from __future__ import annotations

from django.contrib import admin

from apps.health.models import HealthMeasurement


@admin.register(HealthMeasurement)
class HealthMeasurementAdmin(admin.ModelAdmin):
    list_display = ("patient", "kind", "value_num", "unit", "state", "observed_at")
    list_filter = ("kind", "state")
