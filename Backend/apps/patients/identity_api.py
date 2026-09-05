"""Patient-identity resolution review API (spec section 19).

Only holders of ``patient.identity.manage`` may review candidate pairs or
perform a merge. A scan can be triggered for a patient; candidates always
enter PENDING and a human must approve before :meth:`merge` will run.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import PATIENT_IDENTITY_MANAGE, HasPermission
from apps.patients.identity import IdentityMergeService, IdentityResolver
from apps.patients.models import Patient, PatientIdentityCandidate, PatientMergeRecord
from apps.patients.serializers import (
    PatientIdentityCandidateSerializer,
    PatientMergeRecordSerializer,
)


class PatientIdentityCandidateViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = PatientIdentityCandidateSerializer
    permission_classes = [IsAuthenticated, HasPermission.of(PATIENT_IDENTITY_MANAGE)]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        qs = PatientIdentityCandidate.objects.select_related("patient_a", "patient_b")
        status_param = self.request.query_params.get("status", PatientIdentityCandidate.Status.PENDING)
        if status_param != "all":
            qs = qs.filter(status=status_param)
        return qs.order_by("-score", "-created_at")

    @action(detail=False, methods=["post"], url_path=r"scan/(?P<patient_public_id>[0-9a-f-]{36})")
    def scan(self, request: Request, patient_public_id=None) -> Response:
        patient = Patient.objects.filter(public_id=patient_public_id).first()
        if patient is None:
            return Response({"detail": "Patient not found."}, status=status.HTTP_404_NOT_FOUND)
        rows = IdentityResolver().scan_and_record(patient, created_by=request.user)
        return Response(
            PatientIdentityCandidateSerializer(rows, many=True).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def approve(self, request: Request, public_id=None) -> Response:
        candidate = self.get_object()
        IdentityMergeService().review(
            candidate=candidate, decision="approve", by=request.user,
            note=request.data.get("note", ""),
        )
        return Response(PatientIdentityCandidateSerializer(candidate).data)

    @action(detail=True, methods=["post"])
    def reject(self, request: Request, public_id=None) -> Response:
        candidate = self.get_object()
        IdentityMergeService().review(
            candidate=candidate, decision="distinct", by=request.user,
            note=request.data.get("note", ""),
        )
        return Response(PatientIdentityCandidateSerializer(candidate).data)

    @action(detail=True, methods=["post"])
    def merge(self, request: Request, public_id=None) -> Response:
        candidate = self.get_object()
        surviving = None
        if request.data.get("surviving_patient_id"):
            surviving = Patient.objects.filter(
                public_id=request.data["surviving_patient_id"]
            ).first()
        try:
            record = IdentityMergeService().perform_merge(
                candidate=candidate, by=request.user, surviving=surviving
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            PatientMergeRecordSerializer(record).data, status=status.HTTP_200_OK
        )


class PatientMergeRecordViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = PatientMergeRecordSerializer
    permission_classes = [IsAuthenticated, HasPermission.of(PATIENT_IDENTITY_MANAGE)]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    queryset = PatientMergeRecord.objects.select_related(
        "surviving_patient", "merged_patient"
    ).order_by("-created_at")
