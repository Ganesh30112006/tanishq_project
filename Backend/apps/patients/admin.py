from __future__ import annotations

from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("mrn", "family_name", "given_name", "date_of_birth", "sex", "is_active")
    search_fields = ("mrn", "family_name", "given_name")
    list_filter = ("sex", "is_active")
