from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.models import UUIDTimeStampedModel
from apps.patients.models import Patient


class Doctor(UUIDTimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="doctor_profile"
    )
    registration_number = models.CharField(max_length=64, unique=True)
    specialty = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctors_doctor"
        ordering = ["registration_number"]

    def __str__(self) -> str:
        return f"Dr {self.user.get_username()} ({self.registration_number})"


class DoctorPatientAssignment(UUIDTimeStampedModel):
    """The doctor-patient relationship that authorizes clinical access.

    Ending an assignment is a state change, not a delete, so history is
    preserved (spec section 44).
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ENDED = "ENDED", "Ended"

    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="assignments")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="assignments")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    reason = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "doctors_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "patient"],
                condition=Q(status="ACTIVE"),
                name="uq_active_doctor_patient",
            )
        ]
        indexes = [models.Index(fields=["patient", "status"]), models.Index(fields=["doctor", "status"])]

    def __str__(self) -> str:
        return f"{self.doctor_id}->{self.patient_id} [{self.status}]"
