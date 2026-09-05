from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.common.enums import Role
from apps.doctors.models import DoctorPatientAssignment
from apps.doctors.serializers import AssignmentSerializer


class MyAssignmentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """A doctor lists their own active patient assignments.

    Patient detail is fetched via ``/api/v1/patients/`` where scoping and
    object-level authorization already apply.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        user = self.request.user
        if not user.has_role(Role.DOCTOR):
            return DoctorPatientAssignment.objects.none()
        return (
            DoctorPatientAssignment.objects.filter(
                doctor__user_id=user.pk, status=DoctorPatientAssignment.Status.ACTIVE
            )
            .select_related("patient", "doctor")
            .order_by("-assigned_at")
        )
