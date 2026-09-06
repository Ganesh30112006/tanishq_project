"""Approving a model has to mean somebody saw what was still unknown.

The evidence dossier answers eleven questions about a model and, crucially,
records which of them are still open. That record is worth nothing if a model
can reach live clinical use without anyone reading it.

The rule these tests describe is deliberately not "a model with gaps cannot be
approved". Every useful clinical model has gaps, and a rule that blocked them
would not remove the gaps - it would move them out of the record and into
somebody's private judgement, which is exactly where they cannot be audited.

What is blocked is approving *silently*. The approver has to name the open
questions in the transition evidence, which puts them in the lifecycle event
and the audit log. When someone later asks whether anybody knew this model had
never been validated in the population it was used on, the answer is a record
rather than a recollection.
"""
from __future__ import annotations

import pytest

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.common.enums import ModelLifecycleState as S
from apps.common.enums import Role
from apps.common.errors import ValidationFailed
from apps.risk.governance import ModelGovernanceService
from apps.risk.models import FeatureSchema, ModelLifecycleEvent, ModelVersion

pytestmark = pytest.mark.django_db

_INTENDED_USE = {
    "intended_use": "decision support", "target_population": "adults",
    "inclusion_criteria": ["a"], "exclusion_criteria": ["b"],
    "prediction_target": "cvd", "prediction_horizon": "10y",
    "input_requirements": ["age"], "required_data_quality": "observed",
    "acceptable_data_freshness": "365d",
    "validated_domain": {"age": {"min": 40, "max": 79}},
    "known_limitations": ["not validated locally"],
    "output_interpretation": "probability", "contraindications": ["out of domain"],
    "review_requirements": "clinician review",
}


def _dossier(*statuses) -> dict:
    """A dossier where the named questions are open."""
    answers = [{"key": "development_population", "status": "answered",
                "question": "Where was it developed?",
                "answer": "NHANES 1999-2006.", "to_answer_this": ""}]
    for key, status in statuses:
        answers.append({
            "key": key, "status": status,
            "question": f"question about {key}",
            "answer": f"what is known about {key}",
            "to_answer_this": f"a cohort that settles {key}",
        })
    answers.append({"key": "missing_evidence", "status": "answered",
                    "question": "What evidence is still missing?",
                    "answer": "the questions listed above",
                    "to_answer_this": ""})
    open_keys = [key for key, status in statuses if status != "answered"]
    return {
        "questions_version": "evidence-questions-1",
        "answers": answers,
        "status_counts": {
            "answered": len(answers) - len(open_keys),
            "partial": sum(1 for _, s in statuses if s == "partial"),
            "unanswered": sum(1 for _, s in statuses if s == "unanswered"),
        },
        "fully_answered": not open_keys,
    }


def _version(dossier) -> ModelVersion:
    schema = FeatureSchema.objects.create(task="cvd", version="fs-1", definition={})
    return ModelVersion.objects.create(
        model_id="cvd-nhanes-logreg", name="CVD", version="3.1.0", task="cvd",
        feature_schema=schema, calibration_version="cal-1",
        intended_use=dict(_INTENDED_USE),
        validation_metrics={"roc_auc": 0.7653},
        subgroup_metrics={"roc_auc_by_group": {"Age 70-79": 0.5936}},
        evidence_dossier=dossier,
    )


def _walk_to_evaluation(mv, actor):
    gov = ModelGovernanceService()
    for state in (S.VALIDATION, S.APPROVED_FOR_EVALUATION):
        mv = gov.transition(model_version=mv, to_state=state, actor=actor,
                            reason=f"-> {state}")
    return mv


# --- the model has to have a dossier at all -----------------------------
def test_a_version_with_no_dossier_cannot_reach_clinical_use(make_user):
    """No record of what is known is not the same as nothing being unknown."""
    actor = make_user(Role.ADMIN)
    mv = _walk_to_evaluation(_version({}), actor)

    with pytest.raises(ValidationFailed) as excinfo:
        ModelGovernanceService().transition(
            model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW,
            actor=actor, reason="looks fine",
        )
    assert "no evidence dossier" in str(excinfo.value.details["problems"])
    mv.refresh_from_db()
    assert mv.lifecycle_state == S.APPROVED_FOR_EVALUATION


# --- open questions must be named, not merely present -------------------
def test_approval_is_refused_when_the_open_questions_are_not_named(make_user):
    actor = make_user(Role.ADMIN)
    dossier = _dossier(("transportability", "unanswered"), ("calibration", "partial"))
    mv = _walk_to_evaluation(_version(dossier), actor)

    with pytest.raises(ValidationFailed) as excinfo:
        ModelGovernanceService().transition(
            model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW,
            actor=actor, reason="the numbers look good",
        )
    details = excinfo.value.details
    assert set(details["unacknowledged_evidence_gaps"]) == {
        "transportability", "calibration"
    }
    # The refusal has to say what is open and what would close it, or the
    # approver has no way to act on it.
    for row in details["what_is_open"]:
        assert row["question"]
        assert row["to_answer_this"]


def test_acknowledging_only_some_of_the_gaps_is_still_refused(make_user):
    actor = make_user(Role.ADMIN)
    dossier = _dossier(("transportability", "unanswered"), ("calibration", "partial"))
    mv = _walk_to_evaluation(_version(dossier), actor)

    with pytest.raises(ValidationFailed) as excinfo:
        ModelGovernanceService().transition(
            model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW,
            actor=actor, reason="aware of one of them",
            evidence={"acknowledged_evidence_gaps": ["calibration"]},
        )
    assert excinfo.value.details["unacknowledged_evidence_gaps"] == ["transportability"]


def test_a_model_with_open_gaps_can_be_approved_once_they_are_named(make_user):
    """Gaps do not block approval. Approving without seeing them does."""
    actor = make_user(Role.ADMIN)
    dossier = _dossier(("transportability", "unanswered"), ("calibration", "partial"))
    mv = _walk_to_evaluation(_version(dossier), actor)

    mv = ModelGovernanceService().transition(
        model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW, actor=actor,
        reason=(
            "Approved for supervised use with the transportability and "
            "calibration gaps understood; every output is clinician-reviewed."
        ),
        evidence={"acknowledged_evidence_gaps": ["transportability", "calibration"]},
    )
    assert mv.lifecycle_state == S.APPROVED_FOR_CLINICAL_REVIEW


def test_a_fully_answered_dossier_needs_no_acknowledgement(make_user):
    actor = make_user(Role.ADMIN)
    mv = _walk_to_evaluation(_version(_dossier()), actor)

    mv = ModelGovernanceService().transition(
        model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW,
        actor=actor, reason="every question answered",
    )
    assert mv.lifecycle_state == S.APPROVED_FOR_CLINICAL_REVIEW


# --- what was acknowledged has to survive -------------------------------
def test_the_acknowledged_gaps_are_written_into_the_permanent_record(make_user):
    """A later dossier may close a gap; it may not erase that it was open."""
    actor = make_user(Role.ADMIN)
    dossier = _dossier(("transportability", "unanswered"))
    mv = _walk_to_evaluation(_version(dossier), actor)
    ModelGovernanceService().transition(
        model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW, actor=actor,
        reason="approved with the gap understood",
        evidence={"acknowledged_evidence_gaps": ["transportability"]},
    )

    event = ModelLifecycleEvent.objects.filter(
        model_version=mv, to_state=S.APPROVED_FOR_CLINICAL_REVIEW
    ).get()
    assert event.evidence["acknowledged_evidence_gaps"] == ["transportability"]
    assert event.actor == actor
    assert AuditLog.objects.filter(action=audit.MODEL_GOVERNANCE).exists()

    # Evidence accumulates: the dossier is later updated to say the gap closed.
    mv.evidence_dossier = _dossier(("transportability", "answered"))
    mv.save(update_fields=["evidence_dossier"])

    event.refresh_from_db()
    assert event.evidence["acknowledged_evidence_gaps"] == ["transportability"], (
        "the approval record must still show what was open when it was signed"
    )


# --- the helper the rule depends on -------------------------------------
def test_open_questions_exclude_the_derived_summary(make_user):
    mv = _version(_dossier(("calibration", "partial")))
    assert mv.open_evidence_questions() == ["calibration"]


def test_a_version_with_no_dossier_reports_no_open_questions(make_user):
    """Which is why the governance rule checks for the dossier separately.

    An empty list here means "nothing recorded", not "nothing open", and a
    caller that confused the two would wave through exactly the models with no
    evidence at all.
    """
    assert _version({}).open_evidence_questions() == []


# --- reading the record back --------------------------------------------
def test_the_command_reports_a_missing_dossier_as_nothing_known(make_user):
    """Not as "no gaps" - the two look identical if you only print a list."""
    from io import StringIO

    from django.core.management import call_command

    _version({})
    out = StringIO()
    call_command("model_evidence", model="cvd-nhanes-logreg", stdout=out)
    assert "nothing is known about what is known" in out.getvalue()


def test_the_command_names_the_gaps_an_approval_would_have_to_acknowledge(make_user):
    from io import StringIO

    from django.core.management import call_command

    _version(_dossier(("transportability", "unanswered")))
    out = StringIO()
    call_command("model_evidence", model="cvd-nhanes-logreg", gaps_only=True,
                 stdout=out)
    printed = out.getvalue()
    assert "transportability" in printed
    assert "a cohort that settles transportability" in printed
    # A fully answered question is not printed in gaps-only mode.
    assert "Where was it developed?" not in printed
