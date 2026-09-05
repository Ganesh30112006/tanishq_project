from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import VersionedModel
from apps.patients.models import Patient


class Alert(VersionedModel):
    """A workflow alert about a patient.

    Severity is stored as supplied by validated business/workflow policy; this
    model does not infer clinical urgency (spec section 27).
    """

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="alerts")
    category = models.CharField(max_length=60)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=200)
    detail = models.TextField(blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    source_workflow = models.CharField(max_length=60, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "alerts_alert"
        indexes = [models.Index(fields=["patient", "status"]), models.Index(fields=["status", "severity"])]

    def __str__(self) -> str:
        return f"{self.title} [{self.status}]"
