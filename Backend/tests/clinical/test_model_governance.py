"""Clinical model governance (spec sections 4, 5, 54, 55).

A model becomes usable only by a recorded human decision, never because it
was registered or because its tests passed.
"""
from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.audit.models import AuditLog
from apps.common.enums import ModelLifecycleState as S
from apps.common.enums import Role
from apps.common.errors import ValidationFailed
from apps.risk.governance import ModelGovernanceService
from apps.risk.models import FeatureSchema, ModelVersion, RiskAssessment, RiskModel

pytestmark = pytest.mark.django_db

_FULL_INTENDED_USE = {
    "intended_use": "decision support",
    "target_population": "adults",
    "inclusion_criteria": ["a"],
    "exclusion_criteria": ["b"],
    "prediction_target": "cvd",
    "prediction_horizon": "10y",
    "input_requirements": ["age"],
    "required_data_quality": "observed",
    "acceptable_data_freshness": "365d",
    "validated_domain": {"age": {"min": 18, "max": 95}},
    "known_limitations": ["synthetic"],
    "output_interpretation": "probability",
    "contraindications": ["out of domain"],
    "review_requirements": "clinician review",
}


# A dossier in which every question is answered. Most real models will not
# have one - the point of the acknowledgement rule is what happens when they
# do not - so tests that are about something else use this and stay short.
_COMPLETE_DOSSIER = {
    "questions_version": "evidence-questions-1",
    "status_counts": {"answered": 11, "partial": 0, "unanswered": 0},
    "fully_answered": True,
    "answers": [
        {"key": "development_population", "status": "answered"},
        {"key": "missing_evidence", "status": "answered"},
    ],
}


def _draft(*, intended_use=None, metrics=None, subgroups=None, calibration="cal-1",
           dossier=None) -> ModelVersion:
    schema = FeatureSchema.objects.create(task="cvd", version="fs-1", definition={})
    return ModelVersion.objects.create(
        model_id="cvd-logreg", name="CVD", version="1.0.0", task="cvd",
        feature_schema=schema, calibration_version=calibration,
        intended_use=intended_use if intended_use is not None else dict(_FULL_INTENDED_USE),
        validation_metrics=metrics if metrics is not None else {"roc_auc": 0.8},
        subgroup_metrics=subgroups if subgroups is not None else {"by_sex": {"f": 0.79}},
        evidence_dossier=_COMPLETE_DOSSIER if dossier is None else dossier,
    )


def _promote_to_clinical(mv: ModelVersion, actor) -> ModelVersion:
    gov = ModelGovernanceService()
    for state in (S.VALIDATION, S.APPROVED_FOR_EVALUATION, S.APPROVED_FOR_CLINICAL_REVIEW):
        mv = gov.transition(model_version=mv, to_state=state, actor=actor, reason=f"-> {state}")
    return mv


def test_draft_model_cannot_back_an_enabled_task(make_user):
    mv = _draft()
    with pytest.raises(DjangoValidationError):
        RiskModel.objects.create(task="cvd", active_version=mv, is_enabled=True)


def test_illegal_transition_is_refused(make_user):
    mv = _draft()
    with pytest.raises(ValidationFailed):
        ModelGovernanceService().transition(
            model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW,
            actor=make_user(Role.ADMIN), reason="skip the queue",
        )
    mv.refresh_from_db()
    assert mv.lifecycle_state == S.DRAFT


def test_incomplete_intended_use_blocks_leaving_draft(make_user):
    mv = _draft(intended_use={"intended_use": "x"})
    with pytest.raises(ValidationFailed) as exc:
        ModelGovernanceService().transition(
            model_version=mv, to_state=S.VALIDATION, actor=make_user(Role.ADMIN), reason="go",
        )
    assert "missing_intended_use_keys" in exc.value.details


def test_clinical_approval_requires_validation_and_subgroup_evidence(make_user):
    admin = make_user(Role.ADMIN)
    mv = _draft(subgroups={})
    gov = ModelGovernanceService()
    gov.transition(model_version=mv, to_state=S.VALIDATION, actor=admin, reason="v")
    gov.transition(model_version=mv, to_state=S.APPROVED_FOR_EVALUATION, actor=admin, reason="e")
    with pytest.raises(ValidationFailed) as exc:
        gov.transition(
            model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW, actor=admin, reason="c",
        )
    assert "subgroup_metrics is empty" in exc.value.details["problems"]


def test_happy_path_records_events_actor_and_audit(make_user):
    admin = make_user(Role.ADMIN)
    mv = _promote_to_clinical(_draft(), admin)

    assert mv.lifecycle_state == S.APPROVED_FOR_CLINICAL_REVIEW
    assert mv.approved_by_id == admin.pk and mv.approved_at is not None
    assert list(mv.lifecycle_events.values_list("to_state", flat=True)) == [
        S.VALIDATION, S.APPROVED_FOR_EVALUATION, S.APPROVED_FOR_CLINICAL_REVIEW
    ]
    assert AuditLog.objects.filter(action="model.governance").count() == 3

    ModelGovernanceService().activate_for_task(task="cvd", model_version=mv, actor=admin)
    rm = RiskModel.objects.get(task="cvd")
    assert rm.is_enabled and rm.active_version_id == mv.pk


def test_retiring_active_model_disables_task_but_keeps_history(make_user, make_patient):
    admin = make_user(Role.ADMIN)
    mv = _promote_to_clinical(_draft(), admin)
    ModelGovernanceService().activate_for_task(task="cvd", model_version=mv, actor=admin)
    RiskAssessment.objects.create(
        patient=make_patient(), task="cvd", model_version=mv,
        status=RiskAssessment.Status.COMPLETED, outcome_code="OK", input_snapshot={},
    )

    ModelGovernanceService().transition(
        model_version=mv, to_state=S.RETIRED, actor=admin, reason="superseded",
    )
    rm = RiskModel.objects.get(task="cvd")
    assert not rm.is_enabled
    # The historical prediction and its model-version link are untouched.
    assert RiskAssessment.objects.filter(model_version=mv).count() == 1


def test_models_api_requires_governance_permission(auth_client, make_user):
    resp = auth_client(make_user(Role.DOCTOR)).get("/api/v1/risk/models/")
    assert resp.status_code == 403
    assert resp.data["error"]["code"] == "ACCESS_DENIED"


def test_governor_can_transition_via_api(auth_client, make_user):
    admin = make_user(Role.ADMIN)
    mv = _draft()
    client = auth_client(admin)

    resp = client.post(
        f"/api/v1/risk/models/{mv.public_id}/transition/",
        {"to_state": "VALIDATION", "reason": "begin technical validation"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["lifecycle_state"] == "VALIDATION"
    mv.refresh_from_db()
    assert mv.lifecycle_state == S.VALIDATION
