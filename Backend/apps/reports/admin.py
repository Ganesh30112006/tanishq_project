from __future__ import annotations

from django.contrib import admin

from apps.reports.models import (
    Report,
    ReportFinding,
    ReportSchema,
    ReportSection,
    ReportTest,
)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("public_id", "patient", "report_class", "processing_state", "validation_status")
    list_filter = ("report_class", "processing_state", "validation_status")
    readonly_fields = ("file_sha256", "file_size")


admin.site.register(ReportSchema)
admin.site.register(ReportSection)
admin.site.register(ReportTest)
admin.site.register(ReportFinding)
