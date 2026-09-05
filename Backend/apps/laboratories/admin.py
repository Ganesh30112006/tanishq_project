from __future__ import annotations

from django.contrib import admin

from apps.laboratories.models import (
    Laboratory,
    LabOrder,
    LabResult,
    LabResultValidation,
    LabTechnician,
)

admin.site.register(Laboratory)
admin.site.register(LabTechnician)
admin.site.register(LabOrder)
admin.site.register(LabResult)
admin.site.register(LabResultValidation)
