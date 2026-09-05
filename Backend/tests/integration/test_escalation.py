from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.common.enums import MissingDataTaskStatus, Role
from apps.notifications.models import EscalationPolicy, MissingDataTask, Notification
from apps.notifications.services import EscalationService, MissingDataService

pytestmark = pytest.mark.django_db


def test_open_task_sets_sla_from_policy(make_patient):
    task = MissingDataService().open_task(
        patient=make_patient(), requested_data="glucose", reason="needed",
        source_workflow="lab_result",
    )
    policy = EscalationPolicy.objects.get(source_workflow="lab_result")
    assert task.sla_hours == policy.sla_hours
    assert task.due_at is not None


def test_overdue_task_escalates_one_level_per_boundary(make_patient, make_user):
    admin = make_user(Role.ADMIN)  # gives the reassign_role target a recipient
    task = MissingDataService().open_task(
        patient=make_patient(), requested_data="glucose", reason="needed",
        source_workflow="lab_result",
    )
    # Age the task well past both escalation boundaries (24h, 48h).
    MissingDataTask.objects.filter(pk=task.pk).update(
        created_at=timezone.now() - dt.timedelta(hours=60)
    )

    result = EscalationService().evaluate_overdue()
    assert result["escalated"] == 1

    task.refresh_from_db()
    assert task.escalation_level == 2
    assert task.priority == "urgent"
    assert task.assigned_role == Role.ADMIN
    assert task.last_escalated_at is not None
    assert Notification.objects.filter(
        recipient=admin, category="missing_data_escalation"
    ).exists()


def test_escalation_is_not_repeated_for_the_same_level(make_patient):
    task = MissingDataService().open_task(
        patient=make_patient(), requested_data="x", reason="y", source_workflow="lab_result",
    )
    MissingDataTask.objects.filter(pk=task.pk).update(
        created_at=timezone.now() - dt.timedelta(hours=30)  # past step 1 only
    )
    assert EscalationService().evaluate_overdue()["escalated"] == 1
    assert EscalationService().evaluate_overdue()["escalated"] == 0
    task.refresh_from_db()
    assert task.escalation_level == 1


def test_resolved_task_is_not_escalated(make_patient, make_user):
    svc = MissingDataService()
    task = svc.open_task(
        patient=make_patient(), requested_data="x", reason="y", source_workflow="lab_result",
    )
    svc.transition(task=task, status=MissingDataTaskStatus.RESOLVED, by=make_user())
    MissingDataTask.objects.filter(pk=task.pk).update(
        created_at=timezone.now() - dt.timedelta(hours=100)
    )
    assert EscalationService().evaluate_overdue()["escalated"] == 0
