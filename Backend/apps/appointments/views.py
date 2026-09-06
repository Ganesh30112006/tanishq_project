"""Appointment API.

Scoping rule: a patient sees only their own consultations, a clinician only
those they are party to. Neither can reach the other side's list, and the
queryset is narrowed before any row is returned.
"""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    APPOINTMENT_BOOK,
    APPOINTMENT_MANAGE,
    PermissionResolver,
)
from apps.appointments.models import Appointment, AvailabilitySlot
from apps.appointments.serializers import (
    AppointmentCompleteSerializer,
    AppointmentCreateSerializer,
    AppointmentReasonSerializer,
    AppointmentSerializer,
    AvailabilityCreateSerializer,
    AvailabilitySlotSerializer,
)
from apps.appointments.services import AppointmentService, AvailabilityService
from apps.common.errors import AccessDenied, ResourceNotFound
from apps.doctors.models import Doctor
from apps.patients.models import Patient
from apps.risk.models import RiskAssessment


def _doctor_for(user) -> Doctor | None:
    return Doctor.objects.filter(user_id=user.pk, is_active=True).first()


def _patient_for(user) -> Patient | None:
    return Patient.objects.filter(user_id=user.pk, is_active=True).first()


class AvailabilityViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Open consultation times.

    Anyone signed in may browse open future slots - that is the directory a
    patient books from. Only the owning clinician may publish or withdraw one.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AvailabilitySlotSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        qs = (
            AvailabilitySlot.objects.select_related("doctor__user")
            .annotate(
                active_bookings=Count(
                    "appointments",
                    filter=Q(appointments__status__in=Appointment.ACTIVE_STATUSES),
                )
            )
            .order_by("starts_at")
        )
        params = self.request.query_params
        if params.get("mine") == "true":
            doctor = _doctor_for(self.request.user)
            return qs.filter(doctor=doctor) if doctor else qs.none()

        # The public booking directory: open, unbooked, still in the future.
        qs = qs.filter(is_open=True, starts_at__gt=timezone.now(), active_bookings=0)
        doctor_id = params.get("doctor_id")
        if doctor_id:
            qs = qs.filter(doctor__public_id=doctor_id)
        return qs

    def create(self, request: Request) -> Response:
        PermissionResolver.require(request.user, APPOINTMENT_MANAGE)
        doctor = _doctor_for(request.user)
        if doctor is None:
            raise AccessDenied(
                "Your account does not have an active clinician profile.",
                details={"required": "doctor_profile"},
            )
        data = AvailabilityCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        slot = AvailabilityService().publish(
            doctor=doctor,
            starts_at=data.validated_data["starts_at"],
            ends_at=data.validated_data["ends_at"],
        )
        return Response(AvailabilitySlotSerializer(slot).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def withdraw(self, request: Request, public_id=None) -> Response:
        PermissionResolver.require(request.user, APPOINTMENT_MANAGE)
        doctor = _doctor_for(request.user)
        slot = AvailabilitySlot.objects.filter(public_id=public_id).first()
        if slot is None or doctor is None or slot.doctor_id != doctor.pk:
            raise ResourceNotFound("Availability not found.")
        AvailabilityService().withdraw(slot=slot)
        return Response(AvailabilitySlotSerializer(slot).data)


class AppointmentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = AppointmentSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.select_related(
            "patient", "doctor__user", "slot"
        ).order_by("-slot__starts_at")

        clauses = Q(pk__in=[])  # default-deny
        patient = _patient_for(user)
        if patient is not None:
            clauses |= Q(patient=patient)
        doctor = _doctor_for(user)
        if doctor is not None:
            clauses |= Q(doctor=doctor)
        qs = qs.filter(clauses)

        state = self.request.query_params.get("status")
        if state:
            qs = qs.filter(status=state)
        if self.request.query_params.get("upcoming") == "true":
            qs = qs.filter(
                slot__starts_at__gte=timezone.now(), status__in=Appointment.ACTIVE_STATUSES
            )
        return qs

    # -- booking -------------------------------------------------------
    def create(self, request: Request) -> Response:
        PermissionResolver.require(request.user, APPOINTMENT_BOOK)
        patient = _patient_for(request.user)
        if patient is None:
            raise AccessDenied(
                "Your account is not linked to a health record yet.",
                details={"required": "patient_record"},
            )
        data = AppointmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        slot = AvailabilitySlot.objects.filter(
            public_id=data.validated_data["slot_id"], is_open=True
        ).first()
        if slot is None:
            raise ResourceNotFound("That consultation time is not available.")

        assessment = None
        assessment_id = data.validated_data.get("assessment_id")
        if assessment_id:
            # Only the person's own assessment may be attached, so a booking
            # cannot be used to surface someone else's result to a clinician.
            assessment = RiskAssessment.objects.filter(
                public_id=assessment_id, patient=patient
            ).first()
            if assessment is None:
                raise ResourceNotFound("That analysis was not found on your record.")

        appointment = AppointmentService().book(
            patient=patient,
            slot=slot,
            actor=request.user,
            reason=data.validated_data.get("reason", ""),
            assessment=assessment,
        )
        return Response(AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)

    # -- clinician decisions -------------------------------------------
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, public_id=None) -> Response:
        appointment = self._as_doctor(request, public_id)
        AppointmentService().confirm(appointment=appointment, actor=request.user)
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"])
    def decline(self, request: Request, public_id=None) -> Response:
        appointment = self._as_doctor(request, public_id)
        data = AppointmentReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        AppointmentService().decline(
            appointment=appointment, actor=request.user,
            reason=data.validated_data.get("reason", ""),
        )
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"])
    def complete(self, request: Request, public_id=None) -> Response:
        appointment = self._as_doctor(request, public_id)
        data = AppointmentCompleteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        AppointmentService().complete(
            appointment=appointment, actor=request.user,
            note=data.validated_data.get("note", ""),
        )
        return Response(AppointmentSerializer(appointment).data)

    # -- either party ---------------------------------------------------
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, public_id=None) -> Response:
        appointment = self.get_object()  # already scoped to both parties
        data = AppointmentReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        AppointmentService().cancel(
            appointment=appointment, actor=request.user,
            reason=data.validated_data.get("reason", ""),
        )
        return Response(AppointmentSerializer(appointment).data)

    def _as_doctor(self, request: Request, public_id) -> Appointment:
        """Resolve an appointment the caller may act on *as the clinician*."""
        PermissionResolver.require(request.user, APPOINTMENT_MANAGE)
        doctor = _doctor_for(request.user)
        appointment = self.get_queryset().filter(public_id=public_id).first()
        if appointment is None:
            raise ResourceNotFound("Appointment not found.")
        if doctor is None or appointment.doctor_id != doctor.pk:
            raise AccessDenied("Only the clinician on this appointment may do that.")
        return appointment


class DoctorDirectoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Clinicians a patient can choose between when booking.

    Deliberately minimal: a name and a specialty. It exposes no account
    details and no patient information.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = None

    def get_queryset(self):
        return Doctor.objects.select_related("user").filter(is_active=True).order_by(
            "user__full_name"
        )

    def list(self, request: Request, *args, **kwargs) -> Response:
        rows = [
            {
                "id": str(doctor.public_id),
                "full_name": doctor.user.full_name or doctor.user.email,
                "specialty": doctor.specialty,
            }
            for doctor in self.get_queryset()
        ]
        return Response({"count": len(rows), "results": rows})
