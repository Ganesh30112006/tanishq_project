from __future__ import annotations

from django.contrib import admin

from apps.risk.models import (
    ClinicalReview,
    FeatureSchema,
    ModelLifecycleEvent,
    ModelVersion,
    RiskAssessment,
    RiskFactor,
    RiskModel,
)


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("model_id", "version", "task", "lifecycle_state", "approved_at")
    list_filter = ("lifecycle_state", "task")
    # Lifecycle state is moved only through the governance service, never by
    # editing a row here (spec section 54).
    readonly_fields = ("lifecycle_state", "approved_by", "approved_at", "rejected_at", "retired_at")


@admin.register(ModelLifecycleEvent)
class ModelLifecycleEventAdmin(admin.ModelAdmin):
    list_display = ("model_version", "from_state", "to_state", "actor", "created_at")
    list_filter = ("to_state",)
    readonly_fields = [f.name for f in ModelLifecycleEvent._meta.fields]

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "public_id", "patient", "task", "status", "lifecycle_state", "outcome_code", "created_at"
    )
    list_filter = ("status", "lifecycle_state", "task", "reliability_status")
    readonly_fields = [f.name for f in RiskAssessment._meta.fields]

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(ClinicalReview)
class ClinicalReviewAdmin(admin.ModelAdmin):
    list_display = ("assessment", "reviewer", "decision", "created_at")
    list_filter = ("decision",)
    readonly_fields = [f.name for f in ClinicalReview._meta.fields]

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


admin.site.register(FeatureSchema)
admin.site.register(RiskModel)
admin.site.register(RiskFactor)
