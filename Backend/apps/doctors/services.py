from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.common.services import BaseService
from apps.doctors.models import Doctor, DoctorPatientAssignment
from apps.patients.models import Patient


class AssignmentService(BaseService):
    @transaction.atomic
    def assign(self, doctor: Doctor, patient: Patient, *, assigned_by=None, reason: str = "") -> DoctorPatientAssignment:
        existing = DoctorPatientAssignment.objects.filter(
            doctor=doctor, patient=patient, status=DoctorPatientAssignment.Status.ACTIVE
        ).first()
        if existing:
            return existing
        return DoctorPatientAssignment.objects.create(
            doctor=doctor, patient=patient, assigned_by=assigned_by, reason=reason
        )

    @transaction.atomic
    def end(self, assignment: DoctorPatientAssignment, *, reason: str = "") -> DoctorPatientAssignment:
        assignment.status = DoctorPatientAssignment.Status.ENDED
        assignment.ended_at = timezone.now()
        if reason:
            assignment.reason = reason
        assignment.save(update_fields=["status", "ended_at", "reason", "updated_at"])
        return assignment
