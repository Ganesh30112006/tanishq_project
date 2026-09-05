"""Laboratory and lab-technician onboarding (spec section 41).

A technician's laboratory membership is what scopes their workflow queue, so
creating one is an access-control change: gated on ``staff.manage``, audited,
and deactivated rather than deleted so history survives.
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
from apps.laboratories.models import Laboratory, LabTechnician
from apps.laboratories.serializers import (
    LaboratorySerializer,
    LaboratoryWriteSerializer,
    LabTechnicianSerializer,
    LabTechnicianWriteSerializer,
)


class LaboratoryViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, HasPermission.of(STAFF_MANAGE)]
    serializer_class = LaboratorySerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return Laboratory.objects.order_by("code")

    def create(self, request: Request) -> Response:
        data = LaboratoryWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        code = data.validated_data["code"].strip().upper()
        if Laboratory.objects.filter(code__iexact=code).exists():
            raise ValidationFailed("A laboratory with this code already exists.")
        lab = Laboratory.objects.create(
            code=code,
            name=data.validated_data["name"],
            address=data.validated_data.get("address", ""),
        )
        audit_service.record(
            audit.STAFF_CHANGE, actor=request.user, resource=lab,
            metadata={"action": "laboratory.create", "code": lab.code},
        )
        return Response(LaboratorySerializer(lab).data, status=status.HTTP_201_CREATED)


class LabTechnicianViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, HasPermission.of(STAFF_MANAGE)]
    serializer_class = LabTechnicianSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        qs = LabTechnician.objects.select_related("user", "laboratory").order_by(
            "laboratory__code"
        )
        lab_id = self.request.query_params.get("laboratory_id")
        if lab_id:
            qs = qs.filter(laboratory__public_id=lab_id)
        return qs

    def create(self, request: Request) -> Response:
        data = LabTechnicianWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=data.validated_data["user_email"]
        ).first()
        if user is None:
            raise ResourceNotFound("No account exists with that email address.")
        if not user.has_role(Role.LAB_TECHNICIAN):
            raise ValidationFailed(
                "That account does not hold the LAB_TECHNICIAN role. Grant the role first."
            )
        if LabTechnician.objects.filter(user=user).exists():
            raise ValidationFailed("That account is already assigned to a laboratory.")
        lab = Laboratory.objects.filter(
            public_id=data.validated_data["laboratory_id"], is_active=True
        ).first()
        if lab is None:
            raise ResourceNotFound("Laboratory not found.")

        tech = LabTechnician.objects.create(
            user=user, laboratory=lab,
            employee_id=data.validated_data.get("employee_id", ""),
        )
        audit_service.record(
            audit.STAFF_CHANGE, actor=request.user, resource=tech,
            metadata={"action": "technician.create", "user": user.email, "lab": lab.code},
        )
        return Response(LabTechnicianSerializer(tech).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request: Request, public_id=None) -> Response:
        tech = self.get_object()
        tech.is_active = False
        tech.save(update_fields=["is_active", "updated_at"])
        audit_service.record(
            audit.STAFF_CHANGE, actor=request.user, resource=tech,
            metadata={"action": "technician.deactivate"},
        )
        return Response(LabTechnicianSerializer(tech).data)
