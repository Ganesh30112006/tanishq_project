from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.alerts.models import Alert
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.services import BaseService


class AlertService(BaseService):
    @transaction.atomic
    def create(self, *, patient, category: str, title: str, severity: str = Alert.Severity.INFO,
               detail: str = "", source_workflow: str = "", created_by=None) -> Alert:
        alert = Alert.objects.create(
            patient=patient, category=category, title=title, severity=severity,
            detail=detail, source_workflow=source_workflow, created_by=created_by,
        )
        audit_service.record(audit.ALERT_CREATE, actor=created_by, resource=alert,
                             metadata={"category": category, "severity": severity})
        return alert

    @transaction.atomic
    def acknowledge(self, *, alert: Alert, by) -> Alert:
        alert.status = Alert.Status.ACKNOWLEDGED
        alert.acknowledged_by = by
        alert.acknowledged_at = timezone.now()
        alert.save(update_fields=["status", "acknowledged_by", "acknowledged_at", "updated_at"])
        return alert

    @transaction.atomic
    def resolve(self, *, alert: Alert, by) -> Alert:
        alert.status = Alert.Status.RESOLVED
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "resolved_at", "updated_at"])
        return alert
