from __future__ import annotations

import pytest

from apps.common.enums import Role
from apps.notifications.models import MissingDataTask
from apps.notifications.services import MissingDataService
from apps.reconciliation.models import ReconciliationEvent
from apps.reconciliation.services import ReconciliationService

pytestmark = pytest.mark.django_db


def test_lab_tech_sees_tasks_for_their_role_and_scope(
    auth_client, make_lab_tech, make_patient, open_lab_order
):
    tech = make_lab_tech()
    patient = make_patient()
    open_lab_order(tech, patient)  # links the tech's lab to the patient
    MissingDataService().open_task(
        patient=patient, requested_data="glucose", reason="needed", source_workflow="lab_result",
    )

    resp = auth_client(tech.user).get("/api/v1/notifications/tasks/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["requested_data"] == "glucose"


def test_doctor_can_transition_task_for_assigned_patient(
    auth_client, make_doctor, make_patient, assign_patient
):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    task = MissingDataService().open_task(
        patient=patient, requested_data="bp", reason="blocked", source_workflow="risk_assessment",
    )
    client = auth_client(doctor.user)

    r = client.post(f"/api/v1/notifications/tasks/{task.public_id}/acknowledge/")
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.status == "ACKNOWLEDGED"

    r = client.post(f"/api/v1/notifications/tasks/{task.public_id}/resolve/", {"note": "provided"},
                    format="json")
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.status == "RESOLVED" and task.resolution_note == "provided"


def test_reconciliation_events_need_permission_and_can_be_resolved(
    auth_client, make_user, make_doctor, make_patient
):
    patient = make_patient()
    event = ReconciliationService().open_event(
        patient=patient, kind="SAME_DAY_CONFLICT", summary="glucose conflict",
        items=[
            {"resource_type": "ReportTest", "resource_id": "a", "role_in_conflict": "existing"},
            {"resource_type": "ReportTest", "resource_id": "b", "role_in_conflict": "incoming"},
        ],
    )

    assert auth_client(make_doctor().user).get("/api/v1/reconciliation/events/").status_code == 403

    admin = auth_client(make_user(Role.ADMIN))
    listing = admin.get("/api/v1/reconciliation/events/")
    assert listing.status_code == 200 and listing.data["count"] == 1

    r = admin.post(
        f"/api/v1/reconciliation/events/{event.public_id}/resolve/",
        {"resolution": "Kept lab value; report value annotated."}, format="json",
    )
    assert r.status_code == 200
    assert ReconciliationEvent.objects.get(pk=event.pk).status == "RESOLVED"
