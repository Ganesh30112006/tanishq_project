from __future__ import annotations

import pytest

from apps.common.enums import MissingDataTaskStatus, Role
from apps.notifications.models import Notification
from apps.notifications.services import MissingDataService

pytestmark = pytest.mark.django_db


def test_lab_workflow_routes_to_lab_technician(make_patient, make_lab_tech):
    tech = make_lab_tech()
    patient = make_patient()
    task = MissingDataService().open_task(
        patient=patient,
        requested_data="HbA1c",
        reason="Required for cardiovascular risk assessment",
        source_workflow="lab_result",
        assigned_user=tech.user,
    )
    assert task.assigned_role == Role.LAB_TECHNICIAN
    assert task.status == MissingDataTaskStatus.NOTIFIED
    note = Notification.objects.get(recipient=tech.user)
    # Minimum necessary detail only - identifier + action, no clinical values.
    assert patient.mrn in note.body
    assert "HbA1c" not in note.body


def test_clinical_assessment_routes_to_doctor(make_patient, make_doctor, assign_patient):
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    task = MissingDataService().open_task(
        patient=patient,
        requested_data="systolic_bp",
        reason="blocked risk assessment",
        source_workflow="risk_assessment",
        assigned_user=doctor.user,
    )
    assert task.assigned_role == Role.DOCTOR
    body = Notification.objects.get(recipient=doctor.user).body
    assert "cannot be completed" in body


def test_unknown_workflow_defaults_to_admin(make_patient):
    task = MissingDataService().open_task(
        patient=make_patient(),
        requested_data="config",
        reason="system issue",
        source_workflow="something_new",
    )
    assert task.assigned_role == Role.ADMIN
