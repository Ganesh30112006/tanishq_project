"""AI assistant interaction records (spec sections 36-38, 41).

The LLM is not the primary risk predictor and never invents missing medical
facts. Every interaction is recorded: who asked, which patient scope, what
context was provided (by reference, minimized), and the output - which is
never automatically promoted to trusted clinical data.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import UUIDTimeStampedModel
from apps.patients.models import Patient


class AiInteraction(UUIDTimeStampedModel):
    class Kind(models.TextChoices):
        REPORT_SUMMARY = "REPORT_SUMMARY", "Report summarization"
        HISTORY_SUMMARY = "HISTORY_SUMMARY", "Patient-history summarization"
        PLAIN_LANGUAGE = "PLAIN_LANGUAGE", "Plain-language explanation"
        QA = "QA", "Authorized question answering"
        DOC_ASSIST = "DOC_ASSIST", "Document interpretation assistance"

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
        FAILED = "FAILED", "Failed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="ai_interactions"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, null=True, blank=True, related_name="ai_interactions"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)

    prompt_summary = models.CharField(max_length=500, blank=True)
    context_refs = models.JSONField(
        default=list, blank=True, help_text="References to the minimized context provided"
    )
    model_name = models.CharField(max_length=120, blank=True)
    output_text = models.TextField(blank=True)
    output_flags = models.JSONField(
        default=dict, blank=True, help_text="e.g. contains_uncertainty, missing_information"
    )
    correlation_id = models.CharField(max_length=128, blank=True)

    class Meta:
        db_table = "ai_interaction"
        indexes = [models.Index(fields=["patient", "created_at"]), models.Index(fields=["actor", "created_at"])]


class AiKnowledgeDocument(UUIDTimeStampedModel):
    """Approved knowledge the assistant may retrieve over (spec section 36).

    Only ``is_approved`` documents are ever sent to the AI service. This is
    general reference material, never patient data.
    """

    title = models.CharField(max_length=255)
    category = models.CharField(max_length=80, blank=True)
    body = models.TextField()
    source = models.CharField(max_length=255, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_approved = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_knowledge_document"
        indexes = [models.Index(fields=["is_approved", "category"])]

    def __str__(self) -> str:
        return f"{self.title} (v{self.version})"
