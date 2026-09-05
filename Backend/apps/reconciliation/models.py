"""Reconciliation events (spec sections 19, 20).

When material clinical conflict exists the platform preserves BOTH values and
opens a reconciliation event for appropriate review - it never silently
chooses or merges. Potential duplicate patient identities also enter this
controlled workflow rather than being auto-merged.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import ReconciliationStatus
from apps.common.models import UUIDTimeStampedModel
from apps.patients.models import Patient


class ReconciliationEvent(UUIDTimeStampedModel):
    class Kind(models.TextChoices):
        DUPLICATE_REPORT = "DUPLICATE_REPORT", "Duplicate report"
        DUPLICATE_TEST = "DUPLICATE_TEST", "Duplicate test"
        REPEATED_MEASUREMENT = "REPEATED_MEASUREMENT", "Repeated measurement"
        SAME_DAY_CONFLICT = "SAME_DAY_CONFLICT", "Same-day conflicting results"
        UNIT_CONFLICT = "UNIT_CONFLICT", "Conflicting units"
        TIMESTAMP_CONFLICT = "TIMESTAMP_CONFLICT", "Conflicting timestamps"
        STALE_INFORMATION = "STALE_INFORMATION", "Stale information"
        IDENTITY_CONFLICT = "IDENTITY_CONFLICT", "Patient identity conflict"

    patient = models.ForeignKey(
        Patient, on_delete=models.PROTECT, null=True, blank=True, related_name="reconciliation_events"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(
        max_length=12, choices=ReconciliationStatus.choices, default=ReconciliationStatus.OPEN
    )
    summary = models.CharField(max_length=255)
    detected_at = models.DateTimeField(auto_now_add=True)
    detected_by_workflow = models.CharField(max_length=60, blank=True)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "reconciliation_event"
        indexes = [models.Index(fields=["patient", "status"]), models.Index(fields=["kind", "status"])]

    def __str__(self) -> str:
        return f"{self.kind} [{self.status}]"


class ReconciliationItem(UUIDTimeStampedModel):
    """One side of a preserved conflict."""

    event = models.ForeignKey(ReconciliationEvent, on_delete=models.CASCADE, related_name="items")
    resource_type = models.CharField(max_length=60)
    resource_id = models.CharField(max_length=64)
    role_in_conflict = models.CharField(max_length=16, help_text="e.g. A, B, incoming, existing")
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "reconciliation_item"
