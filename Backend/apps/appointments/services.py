"""Booking workflow.

The important rule lives here: confirming an appointment is what grants the
clinician access to that patient's record, and it happens through the same
``AssignmentService`` the rest of the system authorizes against. There is no
second, weaker path to patient data.
"""
from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment, AvailabilitySlot
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.errors import ValidationFailed
from apps.common.services import BaseService
from apps.doctors.services import AssignmentService


class AppointmentService(BaseService):
    def __init__(self, *, assignments: AssignmentService | None = None) -> None:
        self.assignments = assignments or AssignmentService()

    @transaction.atomic
    def book(self, *, patient, slot: AvailabilitySlot, actor, reason: str = "", assessment=None) -> Appointment:
        # Lock the slot so two people cannot take the same time.
        locked = AvailabilitySlot.objects.select_for_update().get(pk=slot.pk)
        if not locked.is_open:
            raise ValidationFailed("That time is no longer available.")
        if locked.starts_at <= timezone.now():
            raise ValidationFailed("That time has already passed.")
        taken = Appointment.objects.filter(
            slot=locked, status__in=Appointment.ACTIVE_STATUSES
        ).exists()
        if taken:
            raise ValidationFailed("That time has just been booked by someone else.")

        appointment = Appointment.objects.create(
            patient=patient,
            doctor=locked.doctor,
            slot=locked,
            reason=reason,
            triggered_by_assessment=assessment,
        )
        audit_service.record(
            audit.APPOINTMENT_CHANGE,
            actor=actor,
            resource=appointment,
            metadata={"action": "book", "starts_at": locked.starts_at.isoformat()},
        )
        return appointment

    @transaction.atomic
    def confirm(self, *, appointment: Appointment, actor) -> Appointment:
        self._require_status(appointment, {Appointment.Status.REQUESTED})
        appointment.status = Appointment.Status.CONFIRMED
        appointment.confirmed_at = timezone.now()
        appointment.resolved_by = actor
        appointment.save(update_fields=["status", "confirmed_at", "resolved_by", "updated_at"])

        # Accepting the consultation is what puts this clinician on the care
        # team; without it they still cannot open the record.
        self.assignments.assign(
            appointment.doctor,
            appointment.patient,
            assigned_by=actor,
            reason=f"Consultation on {appointment.slot.starts_at:%Y-%m-%d}",
        )
        audit_service.record(
            audit.APPOINTMENT_CHANGE, actor=actor, resource=appointment,
            metadata={"action": "confirm"},
        )
        return appointment

    @transaction.atomic
    def decline(self, *, appointment: Appointment, actor, reason: str = "") -> Appointment:
        self._require_status(appointment, {Appointment.Status.REQUESTED})
        return self._close(appointment, Appointment.Status.DECLINED, actor, reason, "decline")

    @transaction.atomic
    def cancel(self, *, appointment: Appointment, actor, reason: str = "") -> Appointment:
        self._require_status(
            appointment, {Appointment.Status.REQUESTED, Appointment.Status.CONFIRMED}
        )
        return self._close(appointment, Appointment.Status.CANCELLED, actor, reason, "cancel")

    @transaction.atomic
    def complete(self, *, appointment: Appointment, actor, note: str = "") -> Appointment:
        self._require_status(appointment, {Appointment.Status.CONFIRMED})
        appointment.status = Appointment.Status.COMPLETED
        appointment.completed_at = timezone.now()
        appointment.outcome_note = note
        appointment.resolved_by = actor
        appointment.save(
            update_fields=["status", "completed_at", "outcome_note", "resolved_by", "updated_at"]
        )
        audit_service.record(
            audit.APPOINTMENT_CHANGE, actor=actor, resource=appointment,
            metadata={"action": "complete"},
        )
        # The care relationship deliberately survives the consultation: a
        # clinician who has seen this patient keeps continuity of care and can
        # still write up notes afterwards. Ending it is an explicit admin act.
        return appointment

    # ------------------------------------------------------------------
    def _close(self, appointment, status, actor, reason, verb) -> Appointment:
        appointment.status = status
        appointment.resolution_reason = reason
        appointment.resolved_by = actor
        appointment.save(
            update_fields=["status", "resolution_reason", "resolved_by", "updated_at"]
        )
        audit_service.record(
            audit.APPOINTMENT_CHANGE, actor=actor, resource=appointment,
            metadata={"action": verb, "reason": reason},
        )
        return appointment

    @staticmethod
    def _require_status(appointment: Appointment, allowed: set[str]) -> None:
        if appointment.status not in allowed:
            raise ValidationFailed(
                f"An appointment that is {appointment.get_status_display().lower()} "
                "cannot be changed this way."
            )


class AvailabilityService(BaseService):
    @transaction.atomic
    def publish(self, *, doctor, starts_at: dt.datetime, ends_at: dt.datetime) -> AvailabilitySlot:
        if ends_at <= starts_at:
            raise ValidationFailed("The end time must be after the start time.")
        if starts_at <= timezone.now():
            raise ValidationFailed("Availability must be in the future.")
        overlapping = AvailabilitySlot.objects.filter(
            doctor=doctor, is_open=True, starts_at__lt=ends_at, ends_at__gt=starts_at
        ).exists()
        if overlapping:
            raise ValidationFailed("That overlaps availability you have already published.")
        return AvailabilitySlot.objects.create(
            doctor=doctor, starts_at=starts_at, ends_at=ends_at
        )

    @transaction.atomic
    def withdraw(self, *, slot: AvailabilitySlot) -> AvailabilitySlot:
        if Appointment.objects.filter(
            slot=slot, status__in=Appointment.ACTIVE_STATUSES
        ).exists():
            raise ValidationFailed(
                "Someone has booked this time. Cancel the appointment first so they are told."
            )
        slot.is_open = False
        slot.save(update_fields=["is_open", "updated_at"])
        return slot
