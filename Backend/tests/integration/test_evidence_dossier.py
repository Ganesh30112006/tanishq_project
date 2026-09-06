"""The dossier has to be able to say "we do not know".

Every other test in this pipeline checks that a measurement is correct. These
check something different and easier to get wrong: that the *absence* of a
measurement survives into the record instead of quietly disappearing.

The failure this file exists to catch has a particular shape. A question whose
artifact is missing, or whose evidence is too thin to support a conclusion,
gets rendered as a confident-sounding sentence, and a reader who does not know
which artifacts exist cannot tell it apart from a real answer. Nothing about
the output looks wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from intelligence.ml_service import acceptance_criteria as AC
from intelligence.ml_service import evidence as EV

ARTIFACTS = Path(__file__).resolve().parents[2] / "intelligence" / "_artifacts"
VERSION = "3.1.0"


@pytest.fixture
def card():
    path = ARTIFACTS / f"cvd-{VERSION}.meta.json"
    if not path.exists():
        pytest.skip("no model artifact built in this checkout")
    return json.loads(path.read_text())


@pytest.fixture
def external():
    path = ARTIFACTS / f"cvd-{VERSION}.external.json"
    if not path.exists():
        pytest.skip("external validation not run in this checkout")
    return json.loads(path.read_text())


# --- the question set is fixed ------------------------------------------
def test_the_question_set_is_the_eleven_questions_in_order():
    """A later model must not get an easier set of questions than an earlier one."""
    assert [q.key for q in EV.QUESTIONS] == [
        "development_population", "validation_populations", "representation",
        "exclusions", "abstention_rate", "abstention_reasons", "discrimination",
        "calibration", "subgroup_variation", "transportability",
        "missing_evidence",
    ]
    assert EV.QUESTIONS[-1].key == EV.DERIVED_KEY
    assert EV.QUESTIONS_VERSION


def test_every_question_states_why_it_matters():
    """A question nobody can justify is a question that gets dropped."""
    for question in EV.QUESTIONS:
        assert len(question.why) > 40, question.key


# --- a missing artifact becomes an unanswered question, not a gap -------
def test_a_model_with_no_artifacts_answers_nothing_and_says_so(tmp_path):
    dossier = EV.build_dossier("0.0.0", artifacts=tmp_path)

    assert dossier["fully_answered"] is False
    assert dossier["status_counts"][EV.ANSWERED] == 1   # only the derived one
    statuses = {a["key"]: a["status"] for a in dossier["answers"]}
    assert all(status == EV.UNANSWERED for key, status in statuses.items()
               if key != EV.DERIVED_KEY)
    # And every one of them says what would answer it.
    for answer in dossier["answers"]:
        if answer["status"] != EV.ANSWERED:
            assert answer["to_answer_this"].strip(), answer["key"]


def test_the_dossier_records_which_artifacts_it_read(tmp_path):
    dossier = EV.build_dossier("0.0.0", artifacts=tmp_path)
    assert set(dossier["sources"]) == {"meta", "clinical", "external"}
    assert all(not source["present"] for source in dossier["sources"].values())


def test_a_present_artifact_is_fingerprinted(card):
    """So a dossier can be tied to the exact artifact it was built from."""
    dossier = EV.build_dossier(VERSION)
    assert dossier["sources"]["meta"]["present"] is True
    assert len(dossier["sources"]["meta"]["sha256_16"]) == 16


# --- question 11 cannot be written by hand ------------------------------
def test_the_missing_evidence_list_is_derived_from_the_other_answers():
    answers = [
        EV.Answer("development_population", EV.ANSWERED, "x", sources=["meta"]),
        EV.Answer("calibration", EV.PARTIAL, "y", to_answer_this="more follow-up"),
        EV.Answer("transportability", EV.UNANSWERED, "z", to_answer_this="a cohort"),
    ]
    derived = EV.derive_missing_evidence(answers)

    listed = {q["key"] for q in derived.evidence["open_questions"]}
    assert listed == {"calibration", "transportability"}
    assert derived.evidence["unanswered"] == ["transportability"]
    assert derived.evidence["partial"] == ["calibration"]


def test_a_dossier_whose_gap_list_disagrees_with_its_measurements_is_rejected():
    """The check that stops a reassuring summary outliving the numbers."""
    answers = [
        EV.Answer("transportability", EV.UNANSWERED, "z", to_answer_this="a cohort"),
        # Hand-written, and wrong: it claims nothing is open.
        EV.Answer(EV.DERIVED_KEY, EV.ANSWERED, "all good",
                  evidence={"open_questions": []}),
    ]
    problems = EV.check_coherent(answers)
    assert any("missing-evidence list does not match" in p for p in problems)


def test_an_unanswered_question_with_no_route_out_of_it_is_rejected():
    answers = [EV.Answer("calibration", EV.PARTIAL, "y")]   # no to_answer_this
    problems = EV.check_coherent(answers)
    assert any("does not say what would answer it" in p for p in problems)


def test_an_answered_question_with_no_source_is_rejected():
    answers = [EV.Answer("discrimination", EV.ANSWERED, "0.76, trust me")]
    problems = EV.check_coherent(answers)
    assert any("names no source artifact" in p for p in problems)


# --- a wide interval is not a conclusion --------------------------------
def _external(auc, ci, events, internal=0.7653):
    return {
        "discrimination": {
            "roc_auc": auc, "roc_auc_ci": list(ci), "events": events,
            "internal_roc_auc": internal, "internal_roc_auc_ci": [0.74, 0.79],
        },
        "discrimination_by_ethnicity": [],
        "calibration_reported": False,
        "replication": [],
    }


def test_transport_is_unanswered_when_the_interval_spans_both_answers(card):
    """The real 3.1.0 situation: comfortable midpoint, uninformative interval."""
    answer = EV._transportability(card, None, _external(0.7116, (0.6611, 0.7604), 97))

    assert answer.status == EV.UNANSWERED
    assert "equally compatible" in answer.answer
    assert answer.to_answer_this.strip()


def test_transport_is_not_claimed_from_a_point_estimate_alone(card):
    """A good-looking AUC on a tiny sample answers nothing."""
    answer = EV._transportability(card, None, _external(0.83, (0.65, 0.96), 7))
    assert answer.status == EV.UNANSWERED


def test_a_narrow_interval_close_to_internal_supports_a_partial_conclusion(card):
    answer = EV._transportability(card, None, _external(0.76, (0.735, 0.785), 400))
    assert answer.status == EV.PARTIAL
    # Still not "answered": calibration transport and the intended population
    # remain untested, and the answer has to say so.
    assert "untested" in answer.answer
    assert answer.to_answer_this.strip()


def test_degraded_discrimination_is_reported_as_a_definite_no(card):
    answer = EV._transportability(card, None, _external(0.60, (0.57, 0.64), 300))
    assert answer.status == EV.ANSWERED
    assert answer.answer.startswith("No.")


# --- subgroup claims use the same floor as the acceptance criteria ------
def test_subgroup_variation_ignores_groups_with_too_few_events(card):
    """Two definitions of the same statistic is how a dossier contradicts itself.

    Computed over every group, the worst relative calibration error for 3.1.0
    is 42% - in a group with 21 events, which supports no conclusion at all.
    The acceptance criteria apply an event floor; so must this.
    """
    answer = EV._subgroup_variation(card, None, None)

    assert answer.evidence["event_floor_for_a_conclusion"] == AC.MIN_SUBGROUP_EVENTS
    for row in answer.evidence["by_group"]:
        assert row["events"] >= AC.MIN_SUBGROUP_EVENTS
    thin = answer.evidence["groups_without_enough_events"]
    for row in thin:
        assert row["events"] < AC.MIN_SUBGROUP_EVENTS
    if thin:
        assert "fewer than" in answer.answer


def test_the_worst_subgroup_error_is_the_same_number_the_criteria_judged(card):
    """The dossier and the acceptance criteria must not disagree on a fact.

    The criteria file records its own observation as text ("worst is Black
    non-Hispanic, 19.4% relative error"). If the dossier names a different
    group or a different number, one of them is wrong and a reader has no way
    to tell which.
    """
    path = ARTIFACTS / f"cvd-{VERSION}.clinical.json"
    if not path.exists():
        pytest.skip("clinical validation not run in this checkout")
    criteria = {row["key"]: row for row in json.loads(path.read_text())["criteria"]}
    observed = criteria["calibration.subgroup_error"]["observed"]
    if "not assessed" in observed:
        pytest.skip("subgroup calibration was not assessable")

    worst = EV._subgroup_variation(card, None, None).evidence["worst_relative_error"]
    assert worst["group"] in observed, (
        f"the dossier's worst-calibrated group is {worst['group']}, the "
        f"criteria recorded {observed!r}"
    )
    assert f"{worst['error']:.1%}" in observed


# --- representation distinguishes "small" from "never recorded" ---------
def test_a_group_the_source_data_had_no_category_for_is_not_reported_as_absent(card):
    """Zero and unrecorded are different, and only one can be fixed by sampling."""
    answer = EV._representation(card, None, None)

    assert answer.status == EV.PARTIAL
    assert answer.evidence["target_population_counted_in_development"] is False
    assert "unknown" in answer.answer
    assert answer.to_answer_this.strip()


# --- the shipped dossier ------------------------------------------------
def test_the_shipped_dossier_is_internally_coherent(card):
    """build_dossier raises rather than emitting an incoherent record."""
    dossier = EV.build_dossier(VERSION)
    assert dossier["model_version"] == VERSION
    assert len(dossier["answers"]) == len(EV.QUESTIONS)


def test_the_shipped_dossier_does_not_claim_the_target_population(card, external):
    dossier = EV.build_dossier(VERSION)
    answers = {a["key"]: a for a in dossier["answers"]}

    assert answers["transportability"]["status"] != EV.ANSWERED, (
        "transportability now reads as established; if that is real, the "
        "report wording that calls it inconclusive must be updated too"
    )
    assert answers["calibration"]["status"] != EV.ANSWERED
    open_keys = {q["key"] for q
                 in answers[EV.DERIVED_KEY]["evidence"]["open_questions"]}
    assert {"transportability", "calibration"} <= open_keys


def test_the_shipped_dossier_reports_abstention_on_both_populations(card, external):
    dossier = EV.build_dossier(VERSION)
    answers = {a["key"]: a for a in dossier["answers"]}
    rate = answers["abstention_rate"]
    assert rate["status"] == EV.ANSWERED
    assert set(rate["evidence"]) >= {"development", "external"}
    for row in rate["evidence"].values():
        assert 0 <= row["abstention_rate"] <= 1


def test_scoring_time_refusals_are_not_confused_with_cohort_construction(card):
    """They remove different people for different reasons.

    Somebody dropped when the dataset was built was never in the model's world.
    Somebody refused at the point of use is in front of a clinician right now
    and gets nothing. Reporting only the second makes the model look as though
    it were built on everybody; reporting them merged makes both
    uninterpretable.
    """
    dossier = EV.build_dossier(VERSION)
    answers = {a["key"]: a for a in dossier["answers"]}
    exclusions = answers["exclusions"]

    assert "stated_exclusion_criteria" in exclusions["evidence"]
    if "refused_at_scoring_time" not in exclusions["evidence"]:
        pytest.skip("clinical validation not run in this checkout")

    refused = exclusions["evidence"]["refused_at_scoring_time"]
    assert refused["refused"] > 0
    assert refused["refused"] < refused["target_population"]
    # The two kinds are named separately in the prose, not summed.
    assert "Separately from construction" in exclusions["answer"]
    # And the construction ladder, when present, is a different key entirely.
    ladder = exclusions["evidence"].get("development_cohort_derivation")
    if ladder is not None:
        assert ladder[0]["remaining"] > refused["target_population"]
