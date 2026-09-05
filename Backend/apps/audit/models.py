"""Append-only audit records (spec section 41).

Audit rows cannot be edited or deleted through the ORM (they inherit
:class:`~apps.common.models.AppendOnlyModel`). They record *that* something
happened and *who* did it - never unnecessary sensitive medical content.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.enums import AuditResult
from apps.common.models import AppendOnlyModel


class AuditLog(AppendOnlyModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor_label = models.CharField(max_length=255, blank=True)
    actor_roles = models.JSONField(default=list, blank=True)

    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100, blank=True, db_index=True)
    resource_id = models.CharField(max_length=64, blank=True, db_index=True)

    result = models.CharField(max_length=16, choices=AuditResult.choices)
    reason = models.CharField(max_length=255, blank=True)

    request_id = models.CharField(max_length=128, blank=True, db_index=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)

    # Only non-sensitive identifiers / flags belong here.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.resource_type}:{self.resource_id} -> {self.result}"
