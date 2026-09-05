"""Scheduled missing-data escalation (spec sections 27, 47)."""
from __future__ import annotations

from apps.jobs.runner import register


@register("missingdata.escalate")
def escalate(payload: dict) -> dict:
    from apps.notifications.services import EscalationService

    return EscalationService().evaluate_overdue(limit=int(payload.get("limit", 500)))
