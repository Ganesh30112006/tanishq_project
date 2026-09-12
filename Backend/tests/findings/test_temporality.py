"""The timeline a detector is entitled to reason over.

The distinction the whole module exists to hold:

    longitudinal data  !=  persistent abnormality

A patient whose eGFR was 92 a year ago and is 58 today has a year of data and
a *new* abnormality. Calling that chronic kidney disease would be wrong in a
way nothing downstream could detect, because a finding reading "possible
chronic kidney disease" looks identical whether ninety days of sustained
abnormality stood behind it or a long date range and one bad day did.

The first version of the check lived inside the chronic kidney disease
detector. It worked, and it would not have survived the next detector someone
wrote. So it is declared in the contract and evaluated by the engine, and
these tests are mostly about detectors that *do not* check their own timeline
still being unable to assert anything they were not shown.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from intelligence.document.contracts import ReferenceStatus
from intelligence.findings import registry
from intelligence.findings.contracts import (
    Confidence,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRequirement,
)
from intelligence.findings.engine import detect
from intelligence.findings.evidence import EvidenceSet, Measurement
from intelligence.findings.history import Observation, Series, build_series
from intelligence.findings.temporal import (
    SINGLE_REPORT,
    Subject,
    TemporalContract,
    TemporalRequirement,
)
from intelligence.knowledge.findings import model as KB_MODEL

R = TemporalRequirement
START = date(2025, 1, 6)

_BASE = {
    "version": "1.0.0",
    "label": "A label",
    "category": "renal",
    "required_evidence": (
        EvidenceRequirement(key="egfr", why="because"),
        EvidenceRequirement(key="creatinine", why="because"),
    ),
    "minimum_evidence": "two values",
    "valid_population": "adults",
    "confidence_policy": "stated",
    "validation_status": DetectorValidation.NOT_VALIDATED,
    "validation_note": "never measured here",
}


def _contract(**over) -> EvidenceContract:
    return EvidenceContract(**{**_BASE, **over})


def _persistent_contract(**over) -> TemporalContract:
    defaults = {
        "requirements": frozenset({
            R.REPEATED_MEASUREMENTS, R.TIME_WINDOW,
            R.PERSISTENT_ABNORMALITY, R.ORDERED_SEQUENCE,
        }),
        "subjects": (Subject("egfr", "below", "must have lasted"),),
        "minimum_observations": 2,
        "minimum_window_days": 90,
        "rationale": "chronic means ninety days.",
    }
    return TemporalContract(**{**defaults, **over})


# --- what a temporal contract may declare ---------------------------
def test_the_default_is_one_report():
    assert SINGLE_REPORT.single_report_only
    assert _contract(
        code="ANEMIA_PATTERN", level=EvidenceLevel.CLINICAL_ABNORMALITY
    ).temporal.single_report_only


def test_a_level_2_pattern_may_only_ever_read_one_report():
    """Whether an abnormality persists is a level-3 question, so a level-2
    pattern is not allowed to ask it."""
    with pytest.raises(ValueError, match="observation on one report"):
        _contract(
            code="REDUCED_EGFR_PATTERN",
            level=EvidenceLevel.CLINICAL_ABNORMALITY,
            temporal=_persistent_contract(),
        )


def test_persistence_without_repetition_is_refused():
    """Being abnormal at both ends needs there to be two ends."""
    with pytest.raises(ValueError, match="needs REPEATED_MEASUREMENTS too"):
        TemporalContract(
            requirements=frozenset({R.PERSISTENT_ABNORMALITY}),
            subjects=(Subject("egfr", "below"),),
            minimum_observations=2,
            rationale="x",
        )


def test_persistence_without_a_direction_is_refused():
    """'Abnormal' without a direction would let a value that swung from low to
    high count as having persisted."""
    with pytest.raises(ValueError, match="needs a direction for every"):
        _persistent_contract(subjects=(Subject("egfr"),))


def test_repetition_without_a_count_is_refused():
    with pytest.raises(ValueError, match="minimum_observations of at least 2"):
        _persistent_contract(minimum_observations=1)


def test_a_window_of_zero_days_is_refused():
    with pytest.raises(ValueError, match="minimum_window_days above zero"):
        _persistent_contract(minimum_window_days=0)


def test_a_contract_beyond_one_report_must_name_its_subjects():
    with pytest.raises(ValueError, match="name them in subjects"):
        _persistent_contract(subjects=())


def test_a_contract_beyond_one_report_must_say_why():
    with pytest.raises(ValueError, match="must say why"):
        _persistent_contract(rationale="  ")


def test_a_single_report_contract_cannot_smuggle_in_a_window():
    with pytest.raises(ValueError, match="cannot also ask for"):
        TemporalContract(minimum_window_days=90)


def test_every_shipped_level_2_detector_reads_one_report():
    for detector in registry.by_level(EvidenceLevel.CLINICAL_ABNORMALITY):
        assert detector.contract.temporal.single_report_only, detector.contract.code


def test_the_contract_can_describe_itself_for_a_result():
    described = _persistent_contract().describe()
    assert "2 measurements" in described
    assert "90 days" in described
    assert "both ends" in described
    assert "ordered dates" in described


# --- evaluating a contract against what is actually there -----------
def _series(values, *, every_days=120, low=60.0):
    observations = [
        Observation(
            analyte="egfr", value=value, unit="mL/min/1.73m2",
            observed_on=START + timedelta(days=i * every_days),
            status=(ReferenceStatus.BELOW if value < low else ReferenceStatus.WITHIN),
            report_id=f"r-{i}", reference_low=low,
        )
        for i, value in enumerate(values)
    ]
    return build_series("egfr", observations)


def _evidence_with(series: Series | None) -> EvidenceSet:
    evidence = EvidenceSet(
        measurements={
            "egfr": Measurement(
                analyte="egfr", value=46.0, unit="mL/min/1.73m2",
                reference_low=60.0, reference_high=None, reference_text="> 60",
                reference_source="fallback-table",
                reference_kind="decision_threshold", status=ReferenceStatus.BELOW,
            )
        }
    )
    if series is not None:
        evidence.series = {"egfr": series}
        evidence.observation_window_days = float(series.span_days)
    return evidence


def _gaps(series, **over):
    return _evidence_with(series).unmet_temporal_requirements(
        _persistent_contract(**over)
    )


def test_a_single_report_satisfies_nothing_beyond_one_report():
    gaps = _gaps(None)
    assert {g.requirement for g in gaps} == {R.REPEATED_MEASUREMENTS}
    assert "2 measurements of egfr are needed and 0 are available" in gaps[0].detail


def test_a_sustained_abnormality_over_the_window_satisfies_everything():
    assert _gaps(_series([52.0, 49.0, 46.0])) == []


def test_a_long_window_with_a_new_abnormality_does_not_satisfy_it():
    """The case the whole module exists for."""
    gaps = _gaps(_series([92.0, 84.0, 46.0]))
    assert {g.requirement for g in gaps} == {R.PERSISTENT_ABNORMALITY}
    assert "not the same as a sustained abnormality" in gaps[0].detail


def test_an_abnormality_that_recovered_does_not_satisfy_it():
    gaps = _gaps(_series([46.0, 72.0, 91.0]))
    assert {g.requirement for g in gaps} == {R.PERSISTENT_ABNORMALITY}


def test_a_sustained_abnormality_over_too_short_a_window_does_not():
    gaps = _gaps(_series([52.0, 49.0, 46.0], every_days=10))
    assert {g.requirement for g in gaps} == {R.TIME_WINDOW}
    assert "these span 20" in gaps[0].detail


def test_results_sharing_a_date_cannot_establish_an_order():
    gaps = _gaps(_series([52.0, 49.0, 46.0], every_days=0))
    assert R.ORDERED_SEQUENCE in {g.requirement for g in gaps}


def test_any_mode_is_satisfied_by_one_subject():
    contract = _persistent_contract(
        subjects=(
            Subject("egfr", "below", "x"),
            Subject("urine_albumin_creatinine_ratio", "above", "y"),
        ),
        subject_mode="any",
    )
    evidence = _evidence_with(_series([52.0, 49.0, 46.0]))
    assert evidence.unmet_temporal_requirements(contract) == []


def test_all_mode_needs_every_subject():
    contract = _persistent_contract(
        subjects=(
            Subject("egfr", "below", "x"),
            Subject("urine_albumin_creatinine_ratio", "above", "y"),
        ),
        subject_mode="all",
    )
    evidence = _evidence_with(_series([52.0, 49.0, 46.0]))
    gaps = evidence.unmet_temporal_requirements(contract)
    assert {g.analyte for g in gaps} == {"urine_albumin_creatinine_ratio"}


def test_when_no_subject_qualifies_every_subject_is_reported():
    """So the result can say what would have been enough, rather than naming
    one arbitrary analyte."""
    contract = _persistent_contract(
        subjects=(
            Subject("egfr", "below", "x"),
            Subject("urine_albumin_creatinine_ratio", "above", "y"),
        ),
    )
    gaps = _evidence_with(None).unmet_temporal_requirements(contract)
    assert {g.analyte for g in gaps} == {"egfr", "urine_albumin_creatinine_ratio"}


# --- the engine holds a detector to its contract --------------------
_CHRONIC = EvidenceContract(
    code="POSSIBLE_TEST_CHRONIC_PATTERN_ONLY",
    version="1.0.0",
    level=EvidenceLevel.CONDITION_LIKELIHOOD,
    label="A test condition needing history",
    category="renal",
    required_evidence=(
        EvidenceRequirement(key="egfr", why="the abnormality"),
        EvidenceRequirement(key="creatinine", why="the corroboration"),
    ),
    minimum_evidence="two eGFR values",
    valid_population="adults",
    confidence_policy="stated",
    validation_status=DetectorValidation.NOT_VALIDATED,
    validation_note="a test fixture, never measured",
    temporal=TemporalContract(
        requirements=frozenset({
            R.REPEATED_MEASUREMENTS, R.TIME_WINDOW, R.PERSISTENT_ABNORMALITY,
        }),
        subjects=(Subject("egfr", "below", "must have lasted"),),
        minimum_observations=2,
        minimum_window_days=90,
        rationale="A fixture standing in for a chronicity criterion.",
    ),
)


class _IgnoresItsTimeline:
    """A detector that never checks. The engine must not let it through."""

    contract = _CHRONIC

    def evaluate(self, evidence):
        from intelligence.findings.base import build_finding

        return build_finding(self.contract, confidence=Confidence.SUPPORTED)


@pytest.fixture
def _knowledge_for_the_fixture():
    entry = KB_MODEL.FindingKnowledge(
        code=_CHRONIC.code,
        canonical_name="A test condition",
        definition="A fixture.",
        plain_explanation="A fixture used only by the tests.",
        must_not_say=("Do not use this outside the tests.",),
    )
    from intelligence.knowledge import findings as KB

    KB._KNOWLEDGE[_CHRONIC.code] = entry
    try:
        yield
    finally:
        KB._KNOWLEDGE.pop(_CHRONIC.code, None)


def test_a_detector_that_never_checks_still_cannot_assert(
    _knowledge_for_the_fixture,
):
    report = detect(_evidence_with(None), detectors=[_IgnoresItsTimeline()])
    finding = report.findings[0]

    assert finding.confidence is Confidence.INSUFFICIENT
    assert not finding.asserts_anything
    assert any("2 measurements of egfr" in m for m in finding.evidence_missing)
    assert any("chronicity criterion" in c for c in finding.caveats)


def test_a_long_window_does_not_let_it_through(_knowledge_for_the_fixture):
    """The failure mode in one test: plenty of history, no sustained
    abnormality, and a detector that would have asserted anyway."""
    evidence = _evidence_with(_series([92.0, 84.0, 46.0]))
    finding = detect(evidence, detectors=[_IgnoresItsTimeline()]).findings[0]

    assert finding.confidence is Confidence.INSUFFICIENT
    assert any("sustained abnormality" in m for m in finding.evidence_missing)


def test_a_downgraded_conclusion_is_not_built_upon(_knowledge_for_the_fixture):
    evidence = _evidence_with(None)
    detect(evidence, detectors=[_IgnoresItsTimeline()])
    assert _CHRONIC.code not in evidence.findings


def test_it_is_allowed_through_once_the_abnormality_has_persisted(
    _knowledge_for_the_fixture,
):
    evidence = _evidence_with(_series([52.0, 49.0, 46.0]))
    finding = detect(evidence, detectors=[_IgnoresItsTimeline()]).findings[0]
    assert finding.confidence is Confidence.SUPPORTED


def test_a_single_report_detector_is_never_touched_by_the_backstop():
    """The guard must not quietly suppress the ordinary case."""
    from intelligence.findings.renal import REDUCED_EGFR

    finding = detect(_evidence_with(None), detectors=[REDUCED_EGFR]).findings[0]
    assert finding.code == "REDUCED_EGFR_PATTERN"
    assert finding.asserts_anything
