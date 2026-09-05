from __future__ import annotations

from django.contrib import admin

from apps.ai.models import AiInteraction, AiKnowledgeDocument


@admin.register(AiInteraction)
class AiInteractionAdmin(admin.ModelAdmin):
    list_display = ("kind", "actor", "patient", "status", "created_at")
    list_filter = ("kind", "status")
    readonly_fields = [f.name for f in AiInteraction._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AiKnowledgeDocument)
class AiKnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "version", "is_approved", "updated_at")
    list_filter = ("is_approved", "category")
    search_fields = ("title", "body")
