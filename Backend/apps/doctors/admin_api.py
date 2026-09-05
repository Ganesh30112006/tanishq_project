"""Staff onboarding: doctor profiles and doctor-patient assignments.

An assignment is not bookkeeping - it is the relationship the authorization
engine reads to decide whether a clinician may open a record
(``apps.authz.relationships.is_assigned_doctor``). Creating and ending one is
therefore an access-control change, gated on ``staff.manage`` and audited.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import STAFF_MANAGE, HasPermission
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import Role
from apps.common.errors import ResourceNotFound, ValidationFailed
from apps.doctors.models import Doctor, DoctorPatientAssignment
from apps.doctors.serializers import (
    AssignmentCreateSerializer,
    AssignmentEndSerializer,
    AssignmentSerializer,
    DoctorSerializer,
    DoctorWriteSerializer,
)
from apps.doctors.services import AssignmentService
from apps.patients.models import Patient


class DoctorAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Create and list clinician profiles."""

    permission_classes = [IsAuthenticated, HasPermission.of(STAFF_MANAGE)]
    serializer_class = DoctorSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return Doctor.objects.select_related("user").order_by("registration_number")

    def create(self, request: Request) -> Response:
        data = DoctorWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = _resolve_staff_user(data.validated_data["user_email"], Role.DOCTOR)
        if Doctor.objects.filter(user=user).exists():
            raise ValidationFailed("That account already has a clinician profile.")

        doctor = Doctor.objects.create(
            user=user,
            registration_number=data.validated_data["registration_number"],
            specialty=data.validated_data.get("specialty", ""),
        )
        audit_service.record(
            audit.STAFF_CHANGE, actor=request.user, resource=doctor,
            metadata={"action": "doctor.create", "user": user.email},
        )
        return Response(DoctorSerializer(doctor).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request: Request, public_id=None) -> Response:
        doctor = self.get_object()
        doctor.is_active = False
        doctor.save(update_fields=["is_active", "updated_at"])
        audit_service.record(
            audit.STAFF_CHANGE, actor=request.user, resource=doctor,
            metadata={"action": "doctor.deactivate"},
        )
        return Response(DoctorSerializer(doctor).data)


class AssignmentAdminViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """Grant or end a clinician's access to a patient."""

    permission_classes = [IsAuthenticated, HasPermission.of(STAFF_MANAGE)]
    serializer_class = AssignmentSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        qs = DoctorPatientAssignment.objects.select_related(
            "doctor__user", "patient"
        ).order_by("-assigned_at")
        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient__public_id=patient_id)
        doctor_id = self.request.query_params.get("doctor_id")
        if doctor_id:
            qs = qs.filter(doctor__public_id=doctor_id)
        state = self.request.query_params.get("status")
        if state:
            qs = qs.filter(status=state)
        return qs

    def create(self, request: Request) -> Response:
        data = AssignmentCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        doctor = Doctor.objects.filter(
            public_id=data.validated_data["doctor_id"], is_active=True
        ).first()
        if doctor is None:
            raise ResourceNotFound("Active clinician profile not found.")
        patient = Patient.objects.filter(
            public_id=data.validated_data["patient_id"], is_active=True
        ).first()
        if patient is None:
            raise ResourceNotFound("Patient not found.")

        assignment = AssignmentService().assign(
            doctor, patient, assigned_by=request.user,
            reason=data.validated_data.get("reason", ""),
        )
        audit_service.record(
            audit.ASSIGNMENT_CHANGE, actor=request.user, resource=assignment,
            metadata={"action": "assign", "doctor": doctor.registration_number},
        )
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="end")
    def end(self, request: Request, public_id=None) -> Response:
        assignment = self.get_object()
        data = AssignmentEndSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ended = AssignmentService().end(assignment, reason=data.validated_data.get("reason", ""))
        audit_service.record(
            audit.ASSIGNMENT_CHANGE, actor=request.user, resource=ended,
            metadata={"action": "end"},
        )
        return Response(AssignmentSerializer(ended).data)


def _resolve_staff_user(email: str, role: str) -> User:
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise ResourceNotFound("No account exists with that email address.")
    if not user.has_role(role):
        raise ValidationFailed(
            f"That account does not hold the {role} role. Grant the role first."
        )
    return user
