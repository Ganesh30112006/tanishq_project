"""Notifications and the missing-data task engine (spec sections 22, 25-27, 45).

Notification bodies carry the minimum necessary detail - never full medical
content. Missing-data tasks have an explicit workflow state and an assigned
role so routing is deterministic.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import LookupState, MissingDataTaskStatus, Role
from apps.common.models import UUIDTimeStampedModel, VersionedModel  # noqa: F401
from apps.patients.models import Patient


class Notification(UUIDTimeStampedModel):
    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-app"
        EMAIL = "EMAIL", "Email"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        READ = "READ", "Read"
        FAILED = "FAILED", "Failed"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.IN_APP)
    category = models.CharField(max_length=60)
    subject = models.CharField(max_length=160)
    body = models.CharField(max_length=500, help_text="Minimum necessary detail only")
    priority = models.CharField(max_length=16, blank=True)

    related_resource_type = models.CharField(max_length=60, blank=True)
    related_resource_id = models.CharField(max_length=64, blank=True)

    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        indexes = [models.Index(fields=["recipient", "status"])]


class MissingDataTask(VersionedModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="missing_data_tasks")
    requested_data = models.CharField(max_length=120)
    reason = models.CharField(max_length=255)
    source_workflow = models.CharField(max_length=60)
    priority = models.CharField(max_length=16, blank=True)

    assigned_role = models.CharField(max_length=20, choices=Role.choices)
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    status = models.CharField(
        max_length=14, choices=MissingDataTaskStatus.choices, default=MissingDataTaskStatus.MISSING
    )
    lookup_state = models.CharField(
        max_length=12, choices=LookupState.choices, default=LookupState.NOT_FOUND
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    due_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True)

    # Escalation state (spec section 27). Escalation is driven by a validated
    # policy, never by a hard-coded medical-urgency assumption.
    escalation_level = models.PositiveIntegerField(default=0)
    last_escalated_at = models.DateTimeField(null=True, blank=True)
    sla_hours = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "notifications_missing_data_task"
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["assigned_role", "status"]),
            models.Index(fields=["status", "due_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.requested_data} for {self.patient_id} [{self.status}]"


class EscalationPolicy(UUIDTimeStampedModel):
    """Configurable escalation policy for missing-data tasks (spec section 27).

    ``steps`` is an ordered list of ``{"after_hours": int, "notify_role":
    "<Role>", "raise_priority_to": "<str>"}``. Priority is derived from
    validated workflow policy, not from arbitrary clinical urgency.
    """

    source_workflow = models.CharField(max_length=60, unique=True)
    sla_hours = models.PositiveIntegerField(default=48)
    steps = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "notifications_escalation_policy"

    def __str__(self) -> str:
        return f"{self.source_workflow} (SLA {self.sla_hours}h)"
