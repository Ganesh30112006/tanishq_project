from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.enums import Role
from apps.notifications.models import MissingDataTask, Notification
from apps.notifications.serializers import (
    MissingDataTaskSerializer,
    MissingDataTaskTransitionSerializer,
    NotificationSerializer,
)
from apps.notifications.services import MissingDataService


class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """A user reads only their own notifications (spec section 5)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, public_id=None):
        notification = self.get_object()
        if notification.status != Notification.Status.READ:
            notification.status = Notification.Status.READ
            notification.read_at = timezone.now()
            notification.save(update_fields=["status", "read_at", "updated_at"])
        return Response(self.get_serializer(notification).data)


class MissingDataTaskViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Missing-data tasks visible to the caller: assigned to them directly, or
    to a role they hold, and always within their patient scope (spec sections
    25-27)."""

    serializer_class = MissingDataTaskSerializer
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.has_role(Role.ADMIN):
            # Operational oversight of the queue itself. Deliberately its own
            # branch rather than a clinical scope: an administrator's clinical
            # scope is empty, and a chase-up task is workflow state.
            return MissingDataTask.objects.select_related("patient").order_by(
                "due_at", "-created_at"
            )

        patient_ids = visible_patient_queryset(user).values_list("pk", flat=True)
        qs = MissingDataTask.objects.filter(patient_id__in=patient_ids).select_related("patient")
        role_codes = list(user.role_codes)
        from django.db.models import Q

        qs = qs.filter(Q(assigned_user=user) | Q(assigned_role__in=role_codes))
        return qs.order_by("due_at", "-created_at")

    def _transition(self, request: Request, target: str | None = None) -> Response:
        task = self.get_object()
        authorize(request.user, Action.UPDATE, task)
        if target is None:
            payload = MissingDataTaskTransitionSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            target = payload.validated_data["status"]
            note = payload.validated_data.get("note", "")
        else:
            note = request.data.get("note", "")
        MissingDataService().transition(task=task, status=target, by=request.user, note=note)
        return Response(MissingDataTaskSerializer(task).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, public_id=None):
        return self._transition(request, "ACKNOWLEDGED")

    @action(detail=True, methods=["post"])
    def start(self, request, public_id=None):
        return self._transition(request, "IN_PROGRESS")

    @action(detail=True, methods=["post"])
    def resolve(self, request, public_id=None):
        return self._transition(request, "RESOLVED")

    @action(detail=True, methods=["post"], url_path="transition")
    def transition(self, request, public_id=None):
        return self._transition(request, None)
