"""Risk-request workflow (spec sections 28, 49, 58).

Ties together the pieces the HTTP view must not contain itself:

1. resolve the active model + feature schema for the task;
2. assemble the required/optional features from the authorized record;
3. run :class:`~apps.risk.services.RiskAssessmentService` (sufficiency ->
   intelligence service -> calibrated result -> store + audit);
4. if the prediction was blocked for missing/stale data, open a
   :class:`~apps.notifications.models.MissingDataTask` per gap - routed to the
   laboratory for lab analytes, to the responsible doctor otherwise - and
   notify the requester that the assessment is blocked.

Authorization and patient resolution happen in the caller (Django owns patient
scope); this service is handed an already-authorized ``patient``.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.common.services import BaseService, ServiceResult
from apps.notifications.services import MissingDataService, NotificationService
from apps.risk.feature_assembly import _LAB_ANALYTE, FeatureAssembler
from apps.risk.models import RiskAssessment, RiskModel
from apps.risk.services import RiskAssessmentService

_MISSING_DATA_OUTCOMES = {"INSUFFICIENT_DATA", "DATA_OUTDATED", "REVIEW_REQUIRED"}


@dataclass(slots=True)
class RiskRequestOutcome:
    assessment: RiskAssessment | None
    result: ServiceResult
    missing_data_tasks: list


class RiskRequestWorkflow(BaseService):
    def __init__(
        self,
        *,
        risk_service: RiskAssessmentService | None = None,
        missing_data: MissingDataService | None = None,
        notifications: NotificationService | None = None,
    ) -> None:
        self.risk_service = risk_service or RiskAssessmentService()
        self.assembler = FeatureAssembler()
        self.missing_data = missing_data or MissingDataService()
        self.notifications = notifications or NotificationService()

    @transaction.atomic
    def request(self, *, actor, patient, task: str, correlation_id: str) -> RiskRequestOutcome:
        model_cfg = (
            RiskModel.objects.select_related("active_version__feature_schema")
            .filter(task=task)
            .first()
        )

        features: dict = {}
        if model_cfg and model_cfg.is_enabled and model_cfg.active_version:
            definition = model_cfg.active_version.feature_schema.definition
            wanted = [f["name"] for f in definition.get("required_features", [])]
            wanted += [f["name"] for f in definition.get("optional_features", [])]
            assembled = self.assembler.assemble(patient=patient, feature_names=wanted)
            features = assembled.values

        result = self.risk_service.assess(
            patient=patient,
            task=task,
            requested_by=actor,
            features=features,
            correlation_id=correlation_id,
        )
        assessment = result.value if isinstance(result.value, RiskAssessment) else None

        tasks: list = []
        if result.failed and result.code in _MISSING_DATA_OUTCOMES:
            tasks = self._open_gap_tasks(
                actor=actor, patient=patient, task=task, result=result
            )
            self.notifications.notify_user(
                recipient=actor,
                category="risk_blocked",
                subject="Risk assessment blocked",
                body=(
                    f"The {task} assessment for Patient {patient.mrn} cannot be completed "
                    f"because required information is unavailable."
                ),
                resource_type="RiskAssessment",
                resource_id=str(assessment.public_id) if assessment else "",
            )

        return RiskRequestOutcome(assessment=assessment, result=result, missing_data_tasks=tasks)

    def _open_gap_tasks(self, *, actor, patient, task: str, result: ServiceResult) -> list:
        gaps = list(result.details.get("missing", [])) + list(result.details.get("stale", []))
        opened = []
        for feature_name in dict.fromkeys(gaps):  # dedupe, preserve order
            lab_backed = feature_name in _LAB_ANALYTE
            opened.append(
                self.missing_data.open_task(
                    patient=patient,
                    requested_data=feature_name,
                    reason=f"Required for the {task} risk assessment",
                    source_workflow="lab_result" if lab_backed else "clinical_assessment",
                    created_by=actor,
                    assigned_user=None if lab_backed else actor,
                )
            )
        return opened
