"""Consultations between a patient and a clinician.

Booking is the consumer path out of the analysis: when the platform tells
someone their results warrant a conversation, this is how that conversation is
arranged. Confirming a booking also establishes the care relationship the
authorization engine reads, so a clinician can only open the record of a
patient who actually booked them.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import UUIDTimeStampedModel
from apps.doctors.models import Doctor
from apps.patients.models import Patient


class AvailabilitySlot(UUIDTimeStampedModel):
    """A block of time a clinician has opened for consultations."""

    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="availability")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    # Withdrawn rather than deleted so a slot that once held a booking keeps
    # its history.
    is_open = models.BooleanField(default=True)

    class Meta:
        db_table = "appointments_availability_slot"
        ordering = ["starts_at"]
        indexes = [models.Index(fields=["doctor", "starts_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "starts_at"], name="uq_doctor_slot_start"
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="ck_slot_ends_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} @ {self.starts_at:%Y-%m-%d %H:%M}"


class Appointment(UUIDTimeStampedModel):
    """A booked consultation.

    Status is a workflow, not a delete: a cancelled or declined appointment
    stays on the record with who ended it and why.
    """

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        CONFIRMED = "CONFIRMED", "Confirmed"
        DECLINED = "DECLINED", "Declined"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    #: Statuses that still hold the slot. A slot is only released when the
    #: appointment reaches a terminal, non-attended state.
    ACTIVE_STATUSES = (Status.REQUESTED, Status.CONFIRMED)

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, related_name="appointments")
    slot = models.ForeignKey(
        AvailabilitySlot, on_delete=models.PROTECT, related_name="appointments"
    )

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    #: Why the patient is seeking a consultation, in their own words. This is a
    #: reported concern, never a diagnosis, and is not treated as clinical fact.
    reason = models.TextField(blank=True)
    #: Set when the booking was prompted by a risk band, so the clinician can
    #: see what the person was shown before they booked.
    triggered_by_assessment = models.ForeignKey(
        "risk.RiskAssessment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )

    outcome_note = models.TextField(blank=True)
    resolution_reason = models.CharField(max_length=255, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "appointments_appointment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
        ]
        constraints = [
            # One live booking per slot; declined/cancelled ones may coexist.
            models.UniqueConstraint(
                fields=["slot"],
                condition=Q(status__in=["REQUESTED", "CONFIRMED"]),
                name="uq_active_appointment_per_slot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.patient_id} with {self.doctor_id} [{self.status}]"
