from __future__ import annotations

from django.contrib import admin

from apps.data_quality.models import AnomalyFlag, DataQualityEvent, DataQualityRule

admin.site.register(DataQualityRule)
admin.site.register(DataQualityEvent)
admin.site.register(AnomalyFlag)
