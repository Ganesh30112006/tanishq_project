"""Health-measurement API (spec sections 5, 9, 42).

OBSERVED/DERIVED measurements require a value; other states record the reason
only. The service rejects fabrication attempts.
"""
from __future__ import annotations

from apps.accounts.permissions import (
    RECORD_READ_ASSIGNED,
    RECORD_READ_OWN,
    PermissionResolver,
)
from apps.common.api import PatientScopedViewSet
from apps.health.models import HealthMeasurement
from apps.health.serializers import (
    HealthMeasurementSerializer,
    HealthMeasurementWriteSerializer,
)
from apps.health.services import HealthMeasurementService

_READ_PERMS = (RECORD_READ_OWN, RECORD_READ_ASSIGNED)


class HealthMeasurementViewSet(PatientScopedViewSet):
    model = HealthMeasurement
    serializer_class = HealthMeasurementSerializer
    write_serializer_class = HealthMeasurementWriteSerializer
    order_by = "-observed_at"

    def get_queryset(self):
        if not PermissionResolver.has_any(self.request.user, *_READ_PERMS):
            return HealthMeasurement.objects.none()
        return super().get_queryset()

    def perform_scoped_create(self, data: dict, patient, actor):
        return HealthMeasurementService().record(patient=patient, entered_by=actor, **data)
