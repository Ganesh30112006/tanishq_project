"""AI assistant API (spec sections 36-38, 42).

* ``POST /api/v1/ai/ask`` - an authorized doctor asks a question about an
  assigned patient. Django authorizes, assembles a minimized patient-scoped
  context, calls the AI service, validates + records the output. **201** when
  an answer was produced, **200** with a structured *blocked* body otherwise
  (no answer is a safe outcome).
* ``GET /api/v1/ai/interactions/`` / ``/{id}/`` - scoped history.
* ``GET /api/v1/ai/knowledge/`` - approved general reference material.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import AI_USE, RECORD_READ_OWN, PermissionResolver
from apps.ai.models import AiInteraction, AiKnowledgeDocument
from apps.ai.serializers import (
    AiAskSerializer,
    AiInteractionSerializer,
    AiKnowledgeDocumentSerializer,
)
from apps.ai.services import AiAssistantService
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.errors import ResourceNotFound
from apps.reports.models import Report


class AiAskView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "ai"

    def post(self, request: Request) -> Response:
        PermissionResolver.require(request.user, AI_USE)

        payload = AiAskSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        patient = (
            visible_patient_queryset(request.user)
            .filter(public_id=data["patient_id"])
            .first()
        )
        if patient is None:
            raise ResourceNotFound("Patient not found or not accessible.")
        authorize(request.user, Action.USE_AI, patient)

        report = None
        if data.get("report_id"):
            report = (
                Report.objects.filter(patient=patient, public_id=data["report_id"])
                .prefetch_related("tests", "findings")
                .first()
            )
            if report is None:
                raise ResourceNotFound("Report not found for this patient.")

        outcome = AiAssistantService().answer(
            actor=request.user,
            patient=patient,
            kind=data["kind"],
            question=data["question"],
            report=report,
            correlation_id=getattr(request, "request_id", ""),
        )
        body = AiInteractionSerializer(outcome.value).data if outcome.value else None
        if outcome.ok:
            return Response(body, status=status.HTTP_201_CREATED)
        return Response(
            {"status": "blocked", "outcome": outcome.code, "message": outcome.message,
             "interaction": body},
            status=status.HTTP_200_OK,
        )


class AiInteractionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = AiInteractionSerializer
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        # An interaction's ``output_text`` restates the clinical record, so
        # reading one is reading the record. Patient scope alone is not enough:
        # a lab technician is inside a patient's scope while an order is open,
        # but is limited to identity fields everywhere else, and must not get
        # the whole picture through this door.
        if not PermissionResolver.has_any(user, AI_USE, RECORD_READ_OWN):
            return AiInteraction.objects.none()
        patient_ids = visible_patient_queryset(user).values_list("pk", flat=True)
        return (
            AiInteraction.objects.filter(patient_id__in=patient_ids)
            .select_related("patient")
            .order_by("-created_at")
        )


class AiKnowledgeViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = AiKnowledgeDocumentSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    queryset = AiKnowledgeDocument.objects.filter(is_approved=True).order_by("title")
