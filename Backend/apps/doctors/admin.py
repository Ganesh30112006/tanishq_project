from __future__ import annotations

from django.contrib import admin

from apps.doctors.models import Doctor, DoctorPatientAssignment


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("registration_number", "specialty", "is_active")
    search_fields = ("registration_number", "user__email")


@admin.register(DoctorPatientAssignment)
class DoctorPatientAssignmentAdmin(admin.ModelAdmin):
    list_display = ("doctor", "patient", "status", "assigned_at", "ended_at")
    list_filter = ("status",)
