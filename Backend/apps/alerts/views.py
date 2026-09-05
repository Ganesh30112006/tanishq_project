"""Alerts API (spec sections 5, 42).

Doctors manage alerts for assigned patients; patients see alerts on their own
record. Severity is stored as supplied by workflow policy - not inferred here.
"""
from __future__ import annotations

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import ALERT_MANAGE, RECORD_READ_OWN, PermissionResolver
from apps.alerts.models import Alert
from apps.alerts.serializers import AlertSerializer, AlertWriteSerializer
from apps.alerts.services import AlertService
from apps.authz.engine import Action, authorize
from apps.common.api import PatientScopedViewSet

alert_service = AlertService()


class AlertViewSet(PatientScopedViewSet):
    model = Alert
    serializer_class = AlertSerializer
    write_serializer_class = AlertWriteSerializer
    select_related = ("patient",)
    audit_action = "alert.create"

    def get_queryset(self):
        # Patient scope alone is not enough here, the same as for records and
        # measurements. A laboratory technician is inside a patient's scope
        # while an order is open, but is limited to identity fields elsewhere -
        # and an alert carries a clinical finding ("systolic readings above
        # target"), so it needs a clinical read permission behind it.
        if not PermissionResolver.has_any(self.request.user, ALERT_MANAGE, RECORD_READ_OWN):
            return Alert.objects.none()
        return super().get_queryset()

    def perform_scoped_create(self, data: dict, patient, actor):
        PermissionResolver.require(actor, ALERT_MANAGE)
        return alert_service.create(patient=patient, created_by=actor, **data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request: Request, public_id=None) -> Response:
        alert = self._for_action(request)
        alert_service.acknowledge(alert=alert, by=request.user)
        return Response(AlertSerializer(alert).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, public_id=None) -> Response:
        alert = self._for_action(request)
        alert_service.resolve(alert=alert, by=request.user)
        return Response(AlertSerializer(alert).data)

    def _for_action(self, request: Request) -> Alert:
        alert = self.get_object()
        PermissionResolver.require(request.user, ALERT_MANAGE)
        authorize(request.user, Action.UPDATE, alert)
        return alert
