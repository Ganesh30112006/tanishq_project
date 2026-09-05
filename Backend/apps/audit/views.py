from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import AUDIT_READ, HasPermission
from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only access to the audit trail for authorized administrators.

    Audit records are never editable through the API (spec section 41).
    """

    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, HasPermission.of(AUDIT_READ)]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    queryset = AuditLog.objects.all().select_related("actor")

    filterset_fields = ["action", "resource_type", "resource_id", "result"]

    def get_queryset(self):
        qs = self.queryset
        params = self.request.query_params
        for field in ("action", "resource_type", "resource_id", "result", "request_id"):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        if since := params.get("since"):
            qs = qs.filter(created_at__gte=since)
        if until := params.get("until"):
            qs = qs.filter(created_at__lte=until)
        return qs
