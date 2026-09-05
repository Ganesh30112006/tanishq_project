"""Reusable DRF building blocks for patient-scoped resources (spec sections 6, 42).

``PatientScopedViewSet`` centralizes the pattern used across records, health,
alerts and lab endpoints: scope the queryset to the caller's visible patients
*before* returning data, and re-check the specific object on write.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import audit_service
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import resolve_visible_patient, visible_patient_queryset
from apps.common.errors import ResourceNotFound


class PatientScopedViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """List/retrieve/create for a model with a ``patient`` FK.

    Subclasses set ``model``, ``serializer_class`` (read) and
    ``write_serializer_class``; optionally ``select_related`` /
    ``prefetch_related`` tuples and ``audit_action``.
    """

    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    model = None
    write_serializer_class = None
    select_related: tuple[str, ...] = ()
    prefetch_related: tuple[str, ...] = ()
    audit_action = "record.modify"
    order_by = "-created_at"

    def get_queryset(self):
        patient_ids = visible_patient_queryset(self.request.user).values_list("pk", flat=True)
        qs = self.model.objects.filter(patient_id__in=patient_ids)
        # Optional narrowing to one patient (e.g. a patient's profile page
        # listing just their own conditions/alerts/measurements). The
        # visibility scoping above has already run, so an id the caller is
        # not authorized for simply yields an empty result, not a leak.
        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient__public_id=patient_id)
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        if self.prefetch_related:
            qs = qs.prefetch_related(*self.prefetch_related)
        return qs.order_by(self.order_by)

    def get_serializer_class(self):
        if self.action == "create" and self.write_serializer_class is not None:
            return self.write_serializer_class
        return self.serializer_class

    def create(self, request: Request, *args, **kwargs) -> Response:
        write = self.get_serializer(data=request.data)
        write.is_valid(raise_exception=True)
        patient_id = write.validated_data.pop("patient_id")
        patient = resolve_visible_patient(request.user, patient_id)
        if patient is None:
            raise ResourceNotFound("Patient not found or not accessible.")
        authorize(request.user, Action.CREATE, self.model(patient=patient))

        instance = self.perform_scoped_create(write.validated_data, patient, request.user)
        audit_service.record(
            self.audit_action, actor=request.user, resource=instance,
            metadata={"action": f"{self.model.__name__.lower()}.create"},
        )
        return Response(self.serializer_class(instance).data, status=status.HTTP_201_CREATED)

    def perform_scoped_create(self, data: dict, patient, actor):
        """Default: create the model row directly. Override to route through a
        service."""
        return self.model.objects.create(patient=patient, **data)
