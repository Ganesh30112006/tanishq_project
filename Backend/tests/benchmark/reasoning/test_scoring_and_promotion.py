"""What the numbers mean, and when they are allowed to mean anything.

Two things are being defended here.

The first is that an abstention is counted honestly. A detector that abstains
on a report the clinician called PRESENT has missed it, and a system that
abstained on everything must score a recall of zero - otherwise "we do not
know" becomes a way of scoring well. But abstaining and asserting absence are
different failures, and the second is more dangerous, so they are also counted
apart.

The second is that a proportion from a handful of observations is not reported
as though it were a proportion. Four out of four is not a recall of 1.0, and
the promotion gate turns on the width of the interval rather than on the point
estimate.
"""
from __future__ import annotations

from datetime import date

import pytest

from intelligence.benchmark import evaluate, readiness, wilson_interval
from intelligence.benchmark.promotion import (
    MIN_CORPUS_REPORTS,
    MIN_NEGATIVE_EVENTS,
    MIN_POSITIVE_EVENTS,
)
from intelligence.benchmark.reasoning import (
    Adjudication,
    BenchmarkItem,
    ConditionAnnotation,
    ConditionSupport,
    Corpus,
    Determination,
    EvidenceSufficiency,
    FindingAnnotation,
    ReportAnnotation,
    score,
)
from intelligence.findings.contracts import Confidence

TODAY = date(2026, 2, 11)
CODE = "ANEMIA_PATTERN"


def _annotation(annotator, report_id, determination, *, conditions=(),
                review=True) -> ReportAnnotation:
    return ReportAnnotation(
        report_id=report_id, report_type="CBC", annotator_id=annotator,
        annotated_on=TODAY,
        applicable_finding_codes=(CODE,),
        applicable_condition_codes=tuple(c.code for c in conditions),
        findings=(FindingAnnotation(
            code=CODE, determination=determination,
            evidence_sufficient=(
                EvidenceSufficiency.INSUFFICIENT
                if determination is Determination.CANNOT_DETERMINE
                else EvidenceSufficiency.SUFFICIENT
            ),
        ),),
        conditions=tuple(conditions),
        human_review_required=review,
    )


def _item(report_id, determination, *, second=None, adjudication=None,
          conditions=()) -> BenchmarkItem:
    annotations = [_annotation("c1", report_id, determination,
                               conditions=conditions)]
    if second is not None:
        annotations.append(_annotation("c2", report_id, second,
                                       conditions=conditions))
    else:
        annotations.append(_annotation("c2", report_id, determination,
                                       conditions=conditions))
    return BenchmarkItem(
        report_id=report_id, report_type="CBC", source_sha256="a" * 64,
        annotations=tuple(annotations), adjudication=adjudication,
    )


def _corpus(*items) -> Corpus:
    return Corpus(corpus_id="test", items=list(items))


# --- the interval behaves at the extremes ---------------------------
def test_four_out_of_four_is_not_a_proportion_of_one():
    low, high = wilson_interval(4, 4)
    assert high == 1.0
    assert low < 0.6, "a normal approximation would give 1.0 and mean nothing"


def test_an_interval_narrows_as_the_evidence_grows():
    small = wilson_interval(8, 10)
    large = wilson_interval(80, 100)
    assert (large[1] - large[0]) < (small[1] - small[0])


def test_no_trials_gives_no_interval_rather_than_zero():
    assert wilson_interval(0, 0) is None


# --- agreement counting ---------------------------------------------
def test_an_asserted_finding_on_a_present_label_is_a_true_positive():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT)),
        {"r-1": {CODE: Confidence.SUPPORTED}},
    )
    assert result.codes[CODE].true_positives == 1
    assert result.codes[CODE].precision == 1.0


def test_an_asserted_finding_on_an_absent_label_is_a_false_positive():
    result = score(
        _corpus(_item("r-1", Determination.ABSENT)),
        {"r-1": {CODE: Confidence.SUPPORTED}},
    )
    assert result.codes[CODE].false_positives == 1
    assert result.codes[CODE].precision == 0.0


def test_silence_on_a_present_label_is_a_false_negative():
    result = score(_corpus(_item("r-1", Determination.PRESENT)), {"r-1": {}})
    entry = result.codes[CODE]
    assert entry.false_negatives == 1
    assert entry.missed_by_abstaining == 0
    assert entry.recall == 0.0


def test_silence_on_an_absent_label_is_a_true_negative():
    result = score(_corpus(_item("r-1", Determination.ABSENT)), {"r-1": {}})
    assert result.codes[CODE].true_negatives == 1


# --- abstention, counted honestly and counted apart -----------------
def test_abstaining_on_a_present_label_is_still_a_miss():
    """Otherwise 'we do not know' becomes a way of scoring well."""
    result = score(
        _corpus(_item("r-1", Determination.PRESENT)),
        {"r-1": {CODE: Confidence.INSUFFICIENT}},
    )
    entry = result.codes[CODE]
    assert entry.false_negatives == 1
    assert entry.recall == 0.0
    # ...but recorded as the softer failure it is.
    assert entry.missed_by_abstaining == 1


def test_a_system_that_abstains_on_everything_scores_zero_recall():
    corpus = _corpus(*[
        _item(f"r-{i}", Determination.PRESENT) for i in range(10)
    ])
    outputs = {f"r-{i}": {CODE: Confidence.INSUFFICIENT} for i in range(10)}
    entry = score(corpus, outputs).codes[CODE]
    assert entry.recall == 0.0
    assert entry.abstention_rate == 1.0


def test_abstaining_where_the_clinician_could_not_determine_is_appropriate():
    """The case where the report genuinely does not settle it. Excluded from
    precision and recall; counted as the thing it actually measures."""
    result = score(
        _corpus(_item("r-1", Determination.CANNOT_DETERMINE)),
        {"r-1": {CODE: Confidence.INSUFFICIENT}},
    )
    entry = result.codes[CODE]
    assert entry.scored == 0
    assert entry.clinician_could_not_determine == 1
    assert entry.appropriate_abstentions == 1
    assert entry.precision is None and entry.recall is None


def test_asserting_where_the_clinician_could_not_determine_is_not_an_abstention():
    result = score(
        _corpus(_item("r-1", Determination.CANNOT_DETERMINE)),
        {"r-1": {CODE: Confidence.SUPPORTED}},
    )
    entry = result.codes[CODE]
    assert entry.clinician_could_not_determine == 1
    assert entry.appropriate_abstentions == 0


# --- unresolved disagreements are excluded and counted --------------
def test_an_unadjudicated_disagreement_is_excluded_from_the_score():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT, second=Determination.ABSENT)),
        {"r-1": {CODE: Confidence.SUPPORTED}},
    )
    entry = result.codes[CODE]
    assert entry.scored == 0
    assert entry.unresolved == 1
    assert result.unresolved_rate == 1.0


def test_an_adjudicated_disagreement_is_scored_against_the_ruling():
    ruling = Adjudication(
        adjudicator_id="c3", adjudicated_on=TODAY,
        findings=(FindingAnnotation(
            code=CODE, determination=Determination.ABSENT,
            evidence_sufficient=EvidenceSufficiency.SUFFICIENT,
        ),),
        disagreement_reason="the printed range was a paediatric one",
    )
    result = score(
        _corpus(_item("r-1", Determination.PRESENT, second=Determination.ABSENT,
                      adjudication=ruling)),
        {"r-1": {CODE: Confidence.SUPPORTED}},
    )
    entry = result.codes[CODE]
    assert entry.false_positives == 1
    assert entry.unresolved == 0


def test_what_each_reader_said_is_kept_for_the_disagreement_report():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT, second=Determination.ABSENT)),
        {},
    )
    examples = result.codes[CODE].examples_of_disagreement
    assert examples and "r-1" in examples[0]


# --- a detector firing outside the annotated scope ------------------
def test_asserting_a_code_nobody_scoped_is_a_defect_not_a_score():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT)),
        {"r-1": {CODE: Confidence.SUPPORTED,
                 "TSH_ELEVATION_PATTERN": Confidence.SUPPORTED}},
    )
    stray = result.codes["TSH_ELEVATION_PATTERN"]
    assert stray.out_of_scope_assertions == 1
    assert stray.scored == 0


def test_abstaining_outside_the_scope_is_not_held_against_anything():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT)),
        {"r-1": {CODE: Confidence.SUPPORTED,
                 "TSH_ELEVATION_PATTERN": Confidence.INSUFFICIENT}},
    )
    assert "TSH_ELEVATION_PATTERN" not in result.codes


# --- level-3 conditions ---------------------------------------------
_IRON = "POSSIBLE_IRON_DEFICIENCY_ANEMIA"


def _condition(support) -> ConditionAnnotation:
    return ConditionAnnotation(code=_IRON, support=support)


def test_a_supported_condition_the_system_asserted_is_a_true_positive():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT,
                      conditions=(_condition(ConditionSupport.SUPPORTED),))),
        {"r-1": {_IRON: Confidence.PROVISIONAL}},
    )
    assert result.codes[_IRON].true_positives == 1


def test_a_condition_the_clinician_called_insufficient_is_scored_apart():
    result = score(
        _corpus(_item("r-1", Determination.PRESENT,
                      conditions=(_condition(ConditionSupport.INSUFFICIENT),))),
        {"r-1": {_IRON: Confidence.INSUFFICIENT}},
    )
    entry = result.codes[_IRON]
    assert entry.scored == 0
    assert entry.appropriate_abstentions == 1


# --- promotion: measured, not good ----------------------------------
def _big_corpus(reports, positives) -> tuple[Corpus, dict]:
    items, outputs = [], {}
    for i in range(reports):
        present = i < positives
        items.append(_item(
            f"r-{i}",
            Determination.PRESENT if present else Determination.ABSENT,
        ))
        outputs[f"r-{i}"] = (
            {CODE: Confidence.SUPPORTED} if present else {}
        )
    return Corpus(corpus_id="big", items=items), outputs


def test_a_perfect_detector_on_a_tiny_corpus_is_not_promotable():
    """This is the whole point of defining the requirements first."""
    corpus, outputs = _big_corpus(reports=10, positives=5)
    decision = evaluate(score(corpus, outputs), CODE)

    assert not decision.promotable
    unmet = {r.key for r in decision.unmet}
    assert "corpus_size" in unmet
    assert "positive_events" in unmet
    assert "negative_events" in unmet


def test_a_detector_measured_at_scale_becomes_promotable():
    corpus, outputs = _big_corpus(reports=MIN_CORPUS_REPORTS, positives=60)
    decision = evaluate(score(corpus, outputs), CODE)

    assert decision.promotable, [r.detail for r in decision.unmet]
    assert "precision" in decision.summary and "recall" in decision.summary


def test_a_poorly_performing_detector_is_still_promotable_when_measured():
    """BENCHMARKED means measured, not good. Leaving a detector unvalidated
    because it scored badly would hide the measurement."""
    corpus, _ = _big_corpus(reports=MIN_CORPUS_REPORTS, positives=60)
    # Assert on every report: perfect recall, dreadful precision.
    outputs = {item.report_id: {CODE: Confidence.SUPPORTED} for item in corpus.items}
    result = score(corpus, outputs)

    assert result.codes[CODE].precision < 0.35
    assert evaluate(result, CODE).promotable


def test_a_single_reader_corpus_is_never_promotable():
    items = [
        BenchmarkItem(
            report_id=f"r-{i}", report_type="CBC", source_sha256="a" * 64,
            annotations=(_annotation("c1", f"r-{i}", Determination.PRESENT),),
        )
        for i in range(MIN_CORPUS_REPORTS)
    ]
    corpus = Corpus(corpus_id="one-reader", items=items)
    outputs = {f"r-{i}": {CODE: Confidence.SUPPORTED} for i in range(MIN_CORPUS_REPORTS)}
    decision = evaluate(score(corpus, outputs), CODE)

    assert not decision.promotable
    assert "double_read" in {r.key for r in decision.unmet}


def test_out_of_scope_assertions_block_promotion_outright():
    corpus, outputs = _big_corpus(reports=MIN_CORPUS_REPORTS, positives=60)
    outputs["r-0"] = {**outputs["r-0"], "TSH_ELEVATION_PATTERN": Confidence.SUPPORTED}
    result = score(corpus, outputs)

    decision = evaluate(result, "TSH_ELEVATION_PATTERN")
    assert not decision.promotable
    assert "no_out_of_scope_assertions" in {r.key for r in decision.unmet}


def test_a_code_that_never_appeared_is_reported_as_never_measured():
    corpus, outputs = _big_corpus(reports=20, positives=10)
    decision = evaluate(score(corpus, outputs), "HYPERKALEMIA_PATTERN")
    assert not decision.promotable
    assert decision.summary == "never measured"


@pytest.mark.parametrize("value", [MIN_POSITIVE_EVENTS, MIN_NEGATIVE_EVENTS])
def test_the_event_minimums_are_stated_rather_than_implied(value):
    assert value >= 30


# --- readiness, which is the honest answer today --------------------
def test_readiness_reports_the_two_layers_separately():
    """Never one number: the layers are fixed by completely different work."""
    state = readiness(None, None)
    assert set(state) == {"extraction", "reasoning"}

    assert state["reasoning"]["reports"] == 0
    assert state["reasoning"]["promotable_codes"] == []
    assert any("No clinician-annotated corpus exists" in line
               for line in state["reasoning"]["blocking"])

    assert state["extraction"]["documents"] == 0
    assert state["extraction"]["ready"] is False


def test_readiness_names_what_is_still_blocking():
    corpus, outputs = _big_corpus(reports=10, positives=5)
    state = readiness(score(corpus, outputs))["reasoning"]
    assert state["reports"] == 10
    assert state["promotable_codes"] == []
    assert any("200 reports" in line or "reports," in line
               for line in state["blocking"])
