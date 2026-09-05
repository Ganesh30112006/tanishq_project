"""Reconciliation review API (spec section 20).

Authorized reviewers see conflict events and resolve or dismiss them.
Conflicting clinical values are never merged here - resolution records the
decision and the underlying rows are left intact.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import RECONCILIATION_MANAGE, HasPermission
from apps.common.enums import ReconciliationStatus
from apps.reconciliation.models import ReconciliationEvent
from apps.reconciliation.serializers import (
    ReconciliationEventSerializer,
    ReconciliationResolveSerializer,
)
from apps.reconciliation.services import ReconciliationService


class ReconciliationEventViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ReconciliationEventSerializer
    permission_classes = [IsAuthenticated, HasPermission.of(RECONCILIATION_MANAGE)]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        qs = ReconciliationEvent.objects.prefetch_related("items").select_related("patient")
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs.order_by("-detected_at")

    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, public_id=None) -> Response:
        event = self.get_object()
        payload = ReconciliationResolveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        ReconciliationService().resolve(
            event=event, by=request.user, resolution=payload.validated_data["resolution"]
        )
        return Response(ReconciliationEventSerializer(event).data)

    @action(detail=True, methods=["post"])
    def dismiss(self, request: Request, public_id=None) -> Response:
        event = self.get_object()
        event.status = ReconciliationStatus.DISMISSED
        event.resolved_by = request.user
        event.resolved_at = timezone.now()
        event.resolution = (request.data.get("reason") or "Dismissed")[:255]
        event.save(update_fields=["status", "resolved_by", "resolved_at", "resolution", "updated_at"])
        return Response(ReconciliationEventSerializer(event).data)
