"""What a person without a clinician is allowed to be told about a result.

The self-service path is the reason these exist: a calibrated probability shown
to a lay reader is read as a verdict, so the presentation is governed by what
the model card actually supports rather than by the template.
"""
from __future__ import annotations

import datetime as pydt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.common.enums import ReliabilityStatus, Role
from apps.risk.interpretation import describe_block, evidence_grade, interpret
from apps.risk.models import RiskAssessment
from apps.risk.plain_language import describe_feature, describe_gaps

pytestmark = pytest.mark.django_db


class _Card:
    """A stand-in model version carrying only its governance record."""

    def __init__(self, *, internal="", external="", intended_use=None, target=""):
        self.validation_dataset_version = internal
        self.external_validation_dataset_version = external
        self.intended_use = intended_use or {}
        self.prediction_target = target


def _result(**kwargs):
    """A stand-in assessment - the reading is pure, so no row is needed."""
    fields = dict(  # noqa: C408 - mirrors the model constructor
        status=RiskAssessment.Status.COMPLETED,
        Status=RiskAssessment.Status,
        calibrated_score=Decimal("0.30"),
        reliability_status=ReliabilityStatus.VALID,
        missing_features=[],
        outcome_code="OK",
        model_version=_Card(),
    )
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def _assessment(patient, user, *, age_minutes: int = 0, **kwargs):
    defaults = dict(  # noqa: C408 - mirrors the model constructor
        patient=patient,
        requested_by=user,
        task="cvd",
        status=RiskAssessment.Status.COMPLETED,
        outcome_code="OK",
        calibrated_score=Decimal("0.30"),
        reliability_status=ReliabilityStatus.VALID,
        input_snapshot={},
    )
    defaults.update(kwargs)
    row = RiskAssessment.objects.create(**defaults)
    if age_minutes:
        # created_at is auto_now_add, so move it explicitly.
        RiskAssessment.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - pydt.timedelta(minutes=age_minutes)
        )
        row.refresh_from_db()
    return row


# --- what the model card is allowed to claim ---------------------------
def test_evidence_grade_is_derived_from_the_governance_record():
    assert evidence_grade(None)["code"] == "NOT_CLINICALLY_VALIDATED"
    assert evidence_grade(_Card())["code"] == "NOT_CLINICALLY_VALIDATED"
    assert evidence_grade(_Card(internal="v1"))["code"] == "INTERNALLY_VALIDATED"
    assert evidence_grade(_Card(internal="v1", external="ext-1"))["code"] == "EXTERNALLY_VALIDATED"


def test_an_unvalidated_model_does_not_show_a_patient_a_number():
    """A figure implies a precision the card explicitly disclaims."""
    reading = interpret(
        _result(calibrated_score=Decimal("0.84"), model_version=_Card()),
        for_clinician=False,
    )
    assert reading["show_score"] is False
    assert reading["score_percent"] is None
    assert reading["band_label"]  # the qualitative band still comes through
    assert reading["score_withheld_reason"]
    assert reading["evidence_grade"]["code"] == "NOT_CLINICALLY_VALIDATED"


def test_a_clinician_always_sees_the_number():
    """Withholding the output from its intended audience breaks decision support."""
    reading = interpret(_result(calibrated_score=Decimal("0.84")), for_clinician=True)
    assert reading["show_score"] is True
    assert reading["score_percent"] == 84


def test_an_externally_validated_in_domain_result_shows_the_number():
    reading = interpret(
        _result(
            calibrated_score=Decimal("0.12"),
            model_version=_Card(internal="v1", external="ext-1"),
        ),
        for_clinician=False,
    )
    assert reading["show_score"] is True
    assert reading["score_percent"] == 12


def test_an_out_of_domain_input_withholds_the_number_even_when_validated():
    reading = interpret(
        _result(
            reliability_status=ReliabilityStatus.LOW_RELIABILITY,
            model_version=_Card(internal="v1", external="ext-1"),
        ),
        for_clinician=False,
    )
    assert reading["show_score"] is False
    assert "edge of the range" in reading["reliability_note"]


def test_an_unspecified_horizon_is_not_implied():
    """Better silence than a timeframe the model never claimed."""
    vague = _result(
        model_version=_Card(
            intended_use={"prediction_horizon": "unspecified (demonstration model)"}
        )
    )
    assert interpret(vague, for_clinician=False)["horizon"] == ""

    stated = _result(model_version=_Card(intended_use={"prediction_horizon": "10 years"}))
    assert interpret(stated, for_clinician=False)["horizon"] == "10 years"


def test_every_reading_says_it_is_not_a_diagnosis():
    for score in ("0.05", "0.35", "0.60", "0.95"):
        reading = interpret(_result(calibrated_score=Decimal(score)), for_clinician=False)
        assert "not a diagnosis" in reading["what_it_does_not_mean"]
        assert reading["next_steps"], "a result with no next step is inert"


def test_an_elevated_result_offers_a_consultation():
    row = _result(calibrated_score=Decimal("0.88"))
    actions = {step["action"] for step in interpret(row)["next_steps"]}
    assert "BOOK_APPOINTMENT" in actions


def test_a_blocked_assessment_has_no_reading():
    assert interpret(
        _result(status=RiskAssessment.Status.BLOCKED, calibrated_score=None)
    ) is None


# --- blocked outcomes explained ----------------------------------------
def test_a_block_names_what_is_missing_in_plain_words():
    row = _result(
        status=RiskAssessment.Status.BLOCKED,
        outcome_code="INSUFFICIENT_DATA",
        calibrated_score=None,
        missing_features=["hba1c", "systolic_bp"],
    )
    block = describe_block(row)
    labels = [gap["label"] for gap in block["data_needed"]]
    assert any("HbA1c" in label for label in labels)
    assert any("BP" in label for label in labels)
    assert block["resolvable_by_patient"] is True
    assert all(gap["how_to_supply"] for gap in block["data_needed"])


def test_out_of_domain_is_not_presented_as_something_to_upload():
    """No amount of uploading brings a record inside the validated range."""
    row = _result(
        status=RiskAssessment.Status.BLOCKED,
        outcome_code="OUT_OF_DOMAIN",
        calibrated_score=None,
        missing_features=["hba1c"],
    )
    assert describe_block(row)["resolvable_by_patient"] is False


def test_an_unknown_feature_gets_no_invented_instruction():
    gap = describe_feature("some_future_biomarker")
    assert gap["label"]  # humanised, not blank
    assert gap["how_to_supply"] == ""


def test_gaps_are_deduplicated_in_order():
    gaps = describe_gaps(["hba1c", "hba1c", "ldl"])
    assert [g["feature"] for g in gaps] == ["hba1c", "ldl"]


# --- staleness ----------------------------------------------------------
def test_a_result_is_flagged_once_newer_results_arrive(
    auth_client, make_user, make_patient, make_measurement
):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    row = _assessment(patient, alice, age_minutes=60 * 48)

    resp = auth_client(alice).get(f"/api/v1/risk/assessments/{row.public_id}/")
    assert resp.data["superseded_by_new_data"] is False

    make_measurement(patient)
    resp = auth_client(alice).get(f"/api/v1/risk/assessments/{row.public_id}/")
    assert resp.data["superseded_by_new_data"] is True


@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 60, "DAILY_CAP": 5})
def test_new_results_lift_the_cooldown(
    auth_client, make_user, make_patient, make_measurement
):
    """The cooldown exists because unchanged inputs give the same answer.

    Once the inputs change that reasoning is gone, and making someone wait to
    see the effect of a result they just supplied inverts the intent.
    """
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    # Scored half an hour ago: well inside the 60-minute cooldown.
    _assessment(patient, alice, age_minutes=30)

    make_measurement(patient)

    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code != 429


# --- the wire contract --------------------------------------------------
def test_the_reading_reaches_the_client(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    row = _assessment(patient, alice, calibrated_score=Decimal("0.88"))

    resp = auth_client(alice).get(f"/api/v1/risk/assessments/{row.public_id}/")
    assert resp.status_code == 200
    reading = resp.data["interpretation"]
    assert reading["band"] == "CRITICAL"
    assert reading["evidence_grade"]["code"]
    assert resp.data["blocked_explanation"] is None


def test_the_timeline_does_not_restate_a_withheld_score(
    auth_client, make_user, make_patient, make_doctor, assign_patient
):
    """A figure suppressed on the result card and printed on the timeline is
    no protection at all."""
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    _assessment(patient, alice, calibrated_score=Decimal("0.88"))

    resp = auth_client(alice).get(f"/api/v1/patients/{patient.public_id}/timeline/")
    assert resp.status_code == 200
    details = " ".join(event["detail"] for event in resp.data)
    assert "88/100" not in details
    assert "Much higher than average" in details

    doctor = make_doctor()
    assign_patient(doctor, patient)
    resp = auth_client(doctor.user).get(f"/api/v1/patients/{patient.public_id}/timeline/")
    details = " ".join(event["detail"] for event in resp.data)
    assert "88/100" in details
