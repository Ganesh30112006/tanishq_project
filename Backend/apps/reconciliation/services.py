from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import ReconciliationStatus
from apps.common.services import BaseService
from apps.reconciliation.models import ReconciliationEvent, ReconciliationItem


class ReconciliationService(BaseService):
    @transaction.atomic
    def open_event(
        self,
        *,
        kind: str,
        summary: str,
        items: list[dict],
        patient=None,
        detected_by_workflow: str = "",
    ) -> ReconciliationEvent:
        """Preserve both sides of a conflict and open a review event
        (spec section 20). ``items`` is a list of
        ``{resource_type, resource_id, role_in_conflict, snapshot}``."""
        event = ReconciliationEvent.objects.create(
            patient=patient, kind=kind, summary=summary[:255],
            detected_by_workflow=detected_by_workflow,
        )
        ReconciliationItem.objects.bulk_create(
            ReconciliationItem(
                event=event,
                resource_type=i["resource_type"],
                resource_id=str(i["resource_id"]),
                role_in_conflict=i.get("role_in_conflict", ""),
                snapshot=i.get("snapshot", {}),
            )
            for i in items
        )
        audit_service.record(
            audit.RECONCILIATION_ACTION, resource=event,
            metadata={"action": "open", "kind": kind, "item_count": len(items)},
        )
        return event

    @transaction.atomic
    def resolve(self, *, event: ReconciliationEvent, by, resolution: str) -> ReconciliationEvent:
        event.status = ReconciliationStatus.RESOLVED
        event.resolved_by = by
        event.resolved_at = timezone.now()
        event.resolution = resolution[:255]
        event.save(update_fields=["status", "resolved_by", "resolved_at", "resolution", "updated_at"])
        audit_service.record(
            audit.RECONCILIATION_ACTION, actor=by, resource=event,
            metadata={"action": "resolve"},
        )
        return event
