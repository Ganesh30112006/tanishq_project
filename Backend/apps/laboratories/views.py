"""Laboratory workflow API (spec sections 5, 6, 42).

Lab technicians work within their laboratory; doctors get read access to their
assigned patients' orders and results. Result entry runs deterministic unit
normalization and triggers data-quality + anomaly assessment.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    LAB_RESULT_ENTER,
    LAB_RESULT_VALIDATE,
    LAB_WORKFLOW_ACCESS,
    USERS_MANAGE,
    PermissionResolver,
)
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.enums import Role
from apps.common.errors import AccessDenied, ResourceNotFound, ValidationFailed
from apps.laboratories.models import Laboratory, LabOrder, LabResult, LabTechnician
from apps.laboratories.serializers import (
    LabOrderCreateSerializer,
    LabOrderSerializer,
    LabResultEntrySerializer,
    LabResultSerializer,
    LabResultValidateSerializer,
)
from apps.laboratories.services import LabResultService
from apps.patients.models import Patient

lab_result_service = LabResultService()


def _tech_lab_ids(user) -> list:
    return list(
        LabTechnician.objects.filter(user_id=user.pk, is_active=True).values_list(
            "laboratory_id", flat=True
        )
    )


class LabOrderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    serializer_class = LabOrderSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        qs = LabOrder.objects.filter(
            patient_id__in=visible_patient_queryset(user).values_list("pk", flat=True)
        ).select_related("patient", "laboratory").prefetch_related("results__validations")
        if user.has_role(Role.LAB_TECHNICIAN) and not user.has_role(Role.ADMIN):
            qs = qs.filter(laboratory_id__in=_tech_lab_ids(user))
        return qs.order_by("-requested_at")

    def create(self, request: Request) -> Response:
        if not PermissionResolver.has_any(request.user, LAB_WORKFLOW_ACCESS, USERS_MANAGE):
            raise AccessDenied(details={"required_permission": LAB_WORKFLOW_ACCESS})
        data = LabOrderCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)

        # A lab order is the act that begins the workflow, so the patient is
        # resolved from active patients (a requisition names the patient); reads
        # afterwards are scoped by the resulting workflow link.
        patient = Patient.objects.filter(
            public_id=data.validated_data["patient_id"], is_active=True
        ).first()
        if patient is None:
            raise ResourceNotFound("Patient not found.")

        lab = self._resolve_lab(request.user, data.validated_data.get("laboratory_id"))
        order = LabOrder.objects.create(
            laboratory=lab, patient=patient, panel=data.validated_data["panel"],
            collected_at=data.validated_data.get("collected_at"),
        )
        audit_service.record(
            audit.LAB_RESULT_CHANGE, actor=request.user, resource=order,
            metadata={"action": "order.create", "panel": order.panel},
        )
        return Response(LabOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _resolve_lab(user, laboratory_id):
        if laboratory_id:
            lab = Laboratory.objects.filter(public_id=laboratory_id, is_active=True).first()
            if lab is None:
                raise ValidationFailed("Unknown laboratory.")
            return lab
        tech = LabTechnician.objects.filter(user_id=user.pk, is_active=True).select_related(
            "laboratory"
        ).first()
        if tech is None:
            raise ValidationFailed("No laboratory could be determined for this user.")
        return tech.laboratory

    @action(detail=True, methods=["post"], url_path="results")
    def enter_result(self, request: Request, public_id=None) -> Response:
        order = self.get_object()
        PermissionResolver.require(request.user, LAB_RESULT_ENTER)
        authorize(request.user, Action.CREATE, LabResult(order=order))

        data = LabResultEntrySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        result = lab_result_service.enter_result(
            order=order, entered_by=request.user, **data.validated_data
        )
        audit_service.record(
            audit.LAB_RESULT_CHANGE, actor=request.user, resource=result,
            metadata={"action": "result.enter", "analyte": result.analyte},
        )
        return Response(LabResultSerializer(result).data, status=status.HTTP_201_CREATED)


class LabResultViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    serializer_class = LabResultSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        qs = LabResult.objects.filter(
            order__patient_id__in=visible_patient_queryset(user).values_list("pk", flat=True)
        ).select_related("order", "order__patient").prefetch_related("validations")
        if user.has_role(Role.LAB_TECHNICIAN) and not user.has_role(Role.ADMIN):
            qs = qs.filter(order__laboratory_id__in=_tech_lab_ids(user))
        return qs.order_by("-recorded_at")

    @action(detail=True, methods=["post"])
    def validate(self, request: Request, public_id=None) -> Response:
        result = self.get_object()
        PermissionResolver.require(request.user, LAB_RESULT_VALIDATE)
        authorize(request.user, Action.VALIDATE, result)

        data = LabResultValidateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        validation = lab_result_service.validate_result(
            lab_result=result, validated_by=request.user, **data.validated_data
        )
        audit_service.record(
            audit.LAB_RESULT_CHANGE, actor=request.user, resource=result,
            metadata={"action": "result.validate", "status": validation.status},
        )
        return Response(LabResultSerializer(result).data)
