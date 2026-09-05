"""Notification + missing-data services (spec sections 25-27, 45, 51).

Routing is workflow-aware and deterministic:

* missing *laboratory* information  -> LAB_TECHNICIAN
* blocked *clinical assessment*     -> responsible DOCTOR
* *administrative/system* issue     -> ADMIN

Notification bodies name the patient by identifier and state only that action
is required - no clinical values.
"""
from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import LookupState, MissingDataTaskStatus, Role
from apps.common.services import BaseService
from apps.notifications.models import EscalationPolicy, MissingDataTask, Notification

# Missing-data task statuses that are still "open" and can be escalated.
OPEN_TASK_STATUSES = (
    MissingDataTaskStatus.MISSING,
    MissingDataTaskStatus.NOTIFIED,
    MissingDataTaskStatus.ACKNOWLEDGED,
    MissingDataTaskStatus.IN_PROGRESS,
)

# source_workflow -> role responsible for supplying the data
WORKFLOW_ROUTING: dict[str, str] = {
    "lab_result": Role.LAB_TECHNICIAN,
    "lab_workflow": Role.LAB_TECHNICIAN,
    "specimen": Role.LAB_TECHNICIAN,
    "risk_assessment": Role.DOCTOR,
    "clinical_assessment": Role.DOCTOR,
    "report_review": Role.DOCTOR,
    "system": Role.ADMIN,
    "configuration": Role.ADMIN,
}


class NotificationService(BaseService):
    @transaction.atomic
    def notify_user(
        self,
        *,
        recipient,
        category: str,
        subject: str,
        body: str,
        priority: str = "",
        resource_type: str = "",
        resource_id: str = "",
    ) -> Notification:
        return Notification.objects.create(
            recipient=recipient,
            category=category,
            subject=subject[:160],
            body=body[:500],
            priority=priority,
            related_resource_type=resource_type,
            related_resource_id=resource_id,
        )

    def route_missing_data(self, task: MissingDataTask) -> Notification | None:
        """Create the minimal notification for a missing-data task, addressed to
        the assigned user when one is known."""
        if task.assigned_user is None:
            return None
        if task.assigned_role == Role.LAB_TECHNICIAN:
            body = f"Required laboratory information is unavailable for Patient {task.patient.mrn}."
        elif task.assigned_role == Role.DOCTOR:
            body = (
                f"An assessment for Patient {task.patient.mrn} cannot be completed because "
                f"required information is unavailable."
            )
        else:
            body = f"A data task for Patient {task.patient.mrn} requires administrative action."
        notification = self.notify_user(
            recipient=task.assigned_user,
            category="missing_data",
            subject="Action required: missing information",
            body=body,
            priority=task.priority,
            resource_type="MissingDataTask",
            resource_id=str(task.public_id),
        )
        updated = MissingDataTask.objects.filter(
            pk=task.pk, status=MissingDataTaskStatus.MISSING
        ).update(status=MissingDataTaskStatus.NOTIFIED)
        if updated:
            task.status = MissingDataTaskStatus.NOTIFIED
        return notification


class MissingDataService(BaseService):
    def __init__(self, *, notifications: NotificationService | None = None) -> None:
        self.notifications = notifications or NotificationService()

    @transaction.atomic
    def open_task(
        self,
        *,
        patient,
        requested_data: str,
        reason: str,
        source_workflow: str,
        lookup_state: str = LookupState.NOT_FOUND,
        priority: str = "",
        created_by=None,
        assigned_user=None,
        due_in_days: int | None = None,
    ) -> MissingDataTask:
        assigned_role = WORKFLOW_ROUTING.get(source_workflow, Role.ADMIN)
        policy = EscalationPolicy.objects.filter(
            source_workflow=source_workflow, is_active=True
        ).first()

        now = timezone.now()
        sla_hours = None
        if due_in_days is not None:
            due_at = now + dt.timedelta(days=due_in_days)
        elif policy is not None:
            sla_hours = policy.sla_hours
            due_at = now + dt.timedelta(hours=policy.sla_hours)
        else:
            due_at = None

        task = MissingDataTask.objects.create(
            patient=patient,
            requested_data=requested_data,
            reason=reason,
            source_workflow=source_workflow,
            priority=priority,
            assigned_role=assigned_role,
            assigned_user=assigned_user,
            lookup_state=lookup_state,
            created_by=created_by,
            due_at=due_at,
            sla_hours=sla_hours,
        )
        audit_service.record(
            audit.MISSING_DATA_ACTION, actor=created_by, resource=task,
            metadata={"action": "open", "requested_data": requested_data, "role": assigned_role},
        )
        self.notifications.route_missing_data(task)
        return task

    @transaction.atomic
    def transition(self, *, task: MissingDataTask, status: str, by=None, note: str = "") -> MissingDataTask:
        task.status = status
        if status == MissingDataTaskStatus.ACKNOWLEDGED and task.acknowledged_at is None:
            task.acknowledged_at = timezone.now()
        if status in (MissingDataTaskStatus.RESOLVED, MissingDataTaskStatus.CLOSED):
            task.resolved_at = timezone.now()
            task.resolution_note = note[:255]
        task.save(update_fields=["status", "acknowledged_at", "resolved_at", "resolution_note", "updated_at"])
        audit_service.record(
            audit.MISSING_DATA_ACTION, actor=by, resource=task,
            metadata={"action": "transition", "status": status},
        )
        return task


class EscalationService(BaseService):
    """Advances overdue missing-data tasks through their configured escalation
    policy (spec section 27). Priority and routing come from validated policy,
    not from hard-coded medical-urgency assumptions.
    """

    def __init__(self, *, notifications: NotificationService | None = None) -> None:
        self.notifications = notifications or NotificationService()

    @transaction.atomic
    def evaluate_overdue(self, *, now: dt.datetime | None = None, limit: int = 500) -> dict:
        now = now or timezone.now()
        policies = {p.source_workflow: p for p in EscalationPolicy.objects.filter(is_active=True)}
        tasks = (
            MissingDataTask.objects.select_related("patient", "assigned_user")
            .filter(status__in=OPEN_TASK_STATUSES)
            .order_by("created_at")[:limit]
        )

        escalated = 0
        for task in tasks:
            policy = policies.get(task.source_workflow)
            if policy is None or not policy.steps:
                continue
            age_hours = (now - task.created_at).total_seconds() / 3600.0
            target_level = 0
            for i, step in enumerate(policy.steps, start=1):
                if age_hours >= float(step.get("after_hours", 0)):
                    target_level = i
            if target_level <= task.escalation_level:
                continue

            step = policy.steps[target_level - 1]
            self._apply_step(task, step, target_level, now)
            escalated += 1
        return {"escalated": escalated}

    def _apply_step(self, task: MissingDataTask, step: dict, level: int, now: dt.datetime) -> None:
        task.escalation_level = level
        task.last_escalated_at = now
        if step.get("raise_priority_to"):
            task.priority = step["raise_priority_to"]
        reassign_role = step.get("reassign_role")
        if reassign_role and reassign_role in Role.values:
            task.assigned_role = reassign_role
            task.assigned_user = None
        task.save(
            update_fields=[
                "escalation_level", "last_escalated_at", "priority",
                "assigned_role", "assigned_user", "updated_at",
            ]
        )
        self._notify(task, step)
        audit_service.record(
            audit.MISSING_DATA_ACTION, resource=task,
            metadata={"action": "escalate", "level": level, "role": task.assigned_role},
        )

    def _notify(self, task: MissingDataTask, step: dict) -> None:
        body = (
            f"A missing-data task for Patient {task.patient.mrn} is overdue "
            f"(escalation level {task.escalation_level}) and requires attention."
        )
        recipients = []
        if task.assigned_user is not None:
            recipients = [task.assigned_user]
        else:
            from apps.accounts.models import User

            recipients = list(
                User.objects.filter(
                    is_active=True, user_roles__role__code=task.assigned_role
                ).distinct()[:10]
            )
        for user in recipients:
            self.notifications.notify_user(
                recipient=user,
                category="missing_data_escalation",
                subject="Overdue: action required",
                body=body,
                priority=task.priority,
                resource_type="MissingDataTask",
                resource_id=str(task.public_id),
            )
