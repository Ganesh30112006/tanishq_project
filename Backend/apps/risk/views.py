"""Risk assessment API (spec sections 28, 42, 49, 57, 58).

* ``POST /api/v1/risk/assessments`` - a doctor requests an assessment for an
  assigned patient. Returns **201** with the assessment when a calibrated
  prediction was produced, or **200** with a structured *blocked* outcome
  (``INSUFFICIENT_DATA`` / ``OUT_OF_DOMAIN`` / ``MODEL_UNAVAILABLE`` / ...).
  A blocked outcome is a successful, safe response - the client is told why
  and which missing-data tasks were opened.
* ``GET /api/v1/risk/assessments`` / ``/{id}`` - patients read their own,
  doctors read their assigned patients'. Scoped before any row is returned.
"""
from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    MODEL_GOVERNANCE_MANAGE,
    RISK_READ_ASSIGNED,
    RISK_READ_OWN,
    RISK_REQUEST,
    RISK_REQUEST_OWN,
    RISK_REVIEW,
    PermissionResolver,
)
from apps.authz.drf import ResourceAccessPermission
from apps.authz.engine import Action, authorize
from apps.authz.relationships import visible_patient_queryset
from apps.common.enums import ModelLifecycleState
from apps.common.errors import AccessDenied, AnalysisCooldown, ResourceNotFound
from apps.risk.freshness import has_new_clinical_input_since
from apps.risk.governance import ModelGovernanceService
from apps.risk.models import ModelVersion, RiskAssessment
from apps.risk.review import ClinicalReviewService
from apps.risk.serializers import (
    ClinicalReviewCreateSerializer,
    ClinicalReviewSerializer,
    ModelTransitionSerializer,
    ModelVersionSerializer,
    RiskAssessmentSerializer,
    RiskRequestSerializer,
)
from apps.risk.workflow import RiskRequestWorkflow

_READ_PERMISSIONS = (RISK_READ_OWN, RISK_READ_ASSIGNED)


class RiskAssessmentViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = RiskAssessmentSerializer
    permission_classes = [IsAuthenticated, ResourceAccessPermission]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        user = self.request.user
        # No administrator bypass: an admin holds no risk-read permission, and
        # letting the role stand in for one handed them every patient's score.
        if not PermissionResolver.has_any(user, *_READ_PERMISSIONS):
            return RiskAssessment.objects.none()
        patient_ids = visible_patient_queryset(user).values_list("pk", flat=True)
        qs = RiskAssessment.objects.filter(patient_id__in=patient_ids)
        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient__public_id=patient_id)
        return (
            qs.select_related("model_version", "patient")
            .prefetch_related("factors", "reviews__reviewer")
            .order_by("-created_at")
        )

    @action(detail=True, methods=["post"])
    def review(self, request: Request, public_id=None) -> Response:
        """A clinician records a decision on a model output (spec sections 39, 40)."""
        assessment = self.get_object()  # object-level authorization runs here
        PermissionResolver.require(request.user, RISK_REVIEW)
        authorize(request.user, Action.UPDATE, assessment)

        payload = ClinicalReviewCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        review_row = ClinicalReviewService().submit(
            assessment=assessment,
            reviewer=request.user,
            decision=payload.validated_data["decision"],
            rationale=payload.validated_data["rationale"],
        )
        assessment.refresh_from_db()
        return Response(
            {
                "review": ClinicalReviewSerializer(review_row).data,
                "assessment": RiskAssessmentSerializer(
                    assessment, context=self.get_serializer_context()
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def create(self, request: Request) -> Response:
        # Either a clinician requesting for an assigned patient, or a person
        # asking about their own record. The resource-level check below is what
        # decides *which* patient either of them may actually target.
        if not PermissionResolver.has_any(request.user, RISK_REQUEST, RISK_REQUEST_OWN):
            raise AccessDenied(details={"required_permission": [RISK_REQUEST, RISK_REQUEST_OWN]})

        payload = RiskRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # Resolve the patient only from what this user is allowed to see, then
        # re-check the specific resource before doing any work.
        patient = (
            visible_patient_queryset(request.user)
            .filter(public_id=payload.validated_data["patient_id"])
            .first()
        )
        if patient is None:
            raise ResourceNotFound("Patient not found or not accessible.")
        authorize(request.user, Action.REQUEST_RISK, patient)

        # Permission says this user may act on this record; consent says this
        # patient agreed to their record being analysed this way. They are
        # different questions and both have to be yes.
        from apps.privacy.models import ConsentPurpose
        from apps.privacy.services import privacy_service

        privacy_service.enforce_if_published(patient, ConsentPurpose.RISK_ANALYSIS)

        # Someone analysing their own record is the self-service path and is
        # paced; a clinician working a caseload is not.
        if patient.user_id == request.user.pk:
            _enforce_self_service_limits(
                user=request.user, patient=patient, task=payload.validated_data["task"]
            )

        outcome = RiskRequestWorkflow().request(
            actor=request.user,
            patient=patient,
            task=payload.validated_data["task"],
            correlation_id=getattr(request, "request_id", ""),
        )

        body = {
            "assessment": (
                RiskAssessmentSerializer(
                    outcome.assessment, context=self.get_serializer_context()
                ).data
                if outcome.assessment
                else None
            ),
            "missing_data_tasks": [str(t.public_id) for t in outcome.missing_data_tasks],
        }
        if outcome.result.ok:
            return Response(body, status=status.HTTP_201_CREATED)

        body.update(
            status="blocked",
            outcome=outcome.result.code,
            message=outcome.result.message,
            details=outcome.result.details,
        )
        return Response(body, status=status.HTTP_200_OK)


class ModelVersionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Governed clinical-model registry (spec sections 5, 54).

    Read and lifecycle transitions require ``model.governance.manage`` (admin).
    Nothing here edits a model's weights - only its governance state.
    """

    serializer_class = ModelVersionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def _require_governor(self) -> None:
        if not PermissionResolver.has(self.request.user, MODEL_GOVERNANCE_MANAGE):
            raise AccessDenied(details={"required_permission": MODEL_GOVERNANCE_MANAGE})

    def get_queryset(self):
        self._require_governor()
        qs = ModelVersion.objects.select_related("feature_schema", "approved_by")
        task = self.request.query_params.get("task")
        if task:
            qs = qs.filter(task=task)
        state = self.request.query_params.get("lifecycle_state")
        if state:
            qs = qs.filter(lifecycle_state=state)
        return qs.order_by("task", "model_id", "-created_at")

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, public_id=None) -> Response:
        self._require_governor()
        model_version = self.get_object()
        payload = ModelTransitionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        service = ModelGovernanceService()
        model_version = service.transition(
            model_version=model_version,
            to_state=payload.validated_data["to_state"],
            actor=request.user,
            reason=payload.validated_data["reason"],
            evidence=payload.validated_data.get("evidence") or {},
        )
        if (
            payload.validated_data.get("activate_task")
            and model_version.lifecycle_state
            == ModelLifecycleState.APPROVED_FOR_CLINICAL_REVIEW
        ):
            service.activate_for_task(
                task=model_version.task, model_version=model_version, actor=request.user
            )
        return Response(ModelVersionSerializer(model_version).data, status=status.HTTP_200_OK)


def _enforce_self_service_limits(*, user, patient, task: str) -> None:
    """Pace a person re-running the analysis on their own record.

    Two separate limits, because they guard different things:

    * a **cooldown** after a result that actually scored - re-running the same
      inputs through a deterministic model cannot change the answer, so this
      costs the user nothing. A *blocked* attempt is exempt: being told data
      was missing and then having to wait an hour to retry after supplying it
      would be perverse.
    * a **daily cap** over every attempt, blocked ones included, so a loop
      cannot be used to hammer the intelligence service.
    """
    import datetime as dt

    from django.conf import settings
    from django.utils import timezone

    limits = settings.SELF_SERVICE_ANALYSIS
    now = timezone.now()

    since = now - dt.timedelta(hours=24)
    attempts = RiskAssessment.objects.filter(
        patient=patient, requested_by=user, created_at__gte=since
    ).count()
    if attempts >= limits["DAILY_CAP"]:
        raise AnalysisCooldown(
            "You have run this analysis the maximum number of times for today. "
            "If something has changed, or you are worried, please book a consultation.",
            details={"limit": limits["DAILY_CAP"], "window_hours": 24},
        )

    cooldown = dt.timedelta(minutes=limits["COOLDOWN_MINUTES"])
    last_scored = (
        RiskAssessment.objects.filter(
            patient=patient,
            requested_by=user,
            task=task,
            status=RiskAssessment.Status.COMPLETED,
        )
        .order_by("-created_at")
        .first()
    )
    if last_scored is not None and now - last_scored.created_at < cooldown:
        # The cooldown's whole justification is that re-running unchanged
        # inputs cannot change the answer. Once new results have landed that
        # reasoning is gone, and making someone wait out a timer to see the
        # effect of a result they just supplied would be the opposite of the
        # intent.
        if has_new_clinical_input_since(patient, last_scored.created_at):
            return
        next_at = last_scored.created_at + cooldown
        raise AnalysisCooldown(
            "You ran this analysis a short while ago. The result will not change "
            "until new results are added to your record.",
            details={
                "next_available_at": next_at.isoformat(),
                "retry_after_seconds": int((next_at - now).total_seconds()),
                "last_result_id": str(last_scored.public_id),
            },
        )
