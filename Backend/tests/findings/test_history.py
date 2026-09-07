"""The same analyte across time.

The case this module exists for::

    eGFR  92 -> 84 -> 71 -> 63     a decline
    eGFR  92 -> 63 -> 94           one odd result between two normal ones

Reporting only the latest value, or only the worst, describes both the same
way. The second is far more often a sample taken while the patient was
dehydrated than the beginning of anything, and the difference decides whether
a person is told they may have a lifelong condition.

What is produced is trend *evidence*. A series says what the numbers did and
never why. Turning persistence into a condition stays a level-3 job, under an
evidence contract, hedged and reviewed - and the tests at the end check that
the chronic kidney disease detector, now that it can finally be satisfied,
still refuses everything it should.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from intelligence.document.contracts import ReferenceStatus, TextSource
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.provenance import build_provenance
from intelligence.document.validation import validate_value
from intelligence.findings.contracts import Confidence, EvidenceTemporality
from intelligence.findings.engine import detect
from intelligence.findings.history import (
    MIN_OBSERVATIONS_FOR_A_DIRECTION,
    Observation,
    Persistence,
    ReportSnapshot,
    Trend,
    build_history,
)
from intelligence.knowledge import variation as VAR

START = date(2025, 1, 6)


class _Record:
    def __init__(self, value, provenance=None):
        self.value = value
        self.provenance = provenance


def _record(label, value, unit, ref=""):
    raw = RawExtraction(
        label=label, value_text=str(value), value=value, unit=unit,
        reference_text=ref, printed_flag="",
        line=f"{label} {value} {unit} {ref}".strip(),
        page=1, char_span=(0, 20), extraction_confidence=0.85,
    )
    return _Record(
        validate_value(raw),
        build_provenance(raw, source_sha256="sha",
                         text_source=TextSource.EMBEDDED_TEXT_LAYER,
                         section="PANEL"),
    )


def _snapshots(label, unit, ref, values, *, every_days=120):
    return [
        ReportSnapshot(
            report_id=f"r-{i}",
            observed_on=START + timedelta(days=i * every_days),
            records=[_record(label, value, unit, ref)],
        )
        for i, value in enumerate(values)
    ]


def _egfr(values, *, every_days=120):
    return build_history(
        _snapshots("eGFR", "mL/min/1.73m2", "> 60", values, every_days=every_days),
        sex="male",
    )


# --- the two sequences that must not look the same ------------------
def test_a_steady_decline_is_reported_as_falling():
    series = _egfr([92.0, 84.0, 71.0, 63.0]).series_for("egfr")
    assert series.trend is Trend.FALLING
    assert series.count == 4
    assert series.span_days == 360


def test_one_odd_result_between_two_normal_ones_is_not_a_decline():
    series = _egfr([92.0, 63.0, 94.0]).series_for("egfr")
    assert series.trend is Trend.FLUCTUATING
    assert series.trend is not Trend.FALLING


def test_a_rising_sequence_is_reported_as_rising():
    series = _egfr([63.0, 71.0, 84.0, 92.0]).series_for("egfr")
    assert series.trend is Trend.RISING


# --- noise is not a trend -------------------------------------------
def test_moves_smaller_than_ordinary_variation_are_stable():
    """A creatinine of 88 -> 92 -> 90 has not gone anywhere."""
    history = build_history(
        _snapshots("S. Creatinine", "umol/L", "62 - 106", [88.0, 92.0, 90.0])
    )
    series = history.series_for("creatinine")
    assert series.trend is Trend.STABLE


def test_the_threshold_used_is_stated_in_the_caveats():
    series = _egfr([92.0, 84.0, 71.0]).series_for("egfr")
    assert any("%" in c and "variation expected" in c for c in series.caveats)
    assert series.variation_table_version == VAR.VARIATION_TABLE_VERSION


def test_the_threshold_differs_by_analyte_because_the_analytes_do():
    assert VAR.significant_fraction("sodium") < VAR.significant_fraction("tsh")
    assert VAR.significant_fraction("unheard-of") == VAR.DEFAULT_SIGNIFICANT_FRACTION


# --- two points are a comparison, not a direction -------------------
def test_two_observations_do_not_establish_a_direction():
    series = _egfr([92.0, 63.0]).series_for("egfr")
    assert series.count == 2
    assert series.trend is Trend.INSUFFICIENT
    assert MIN_OBSERVATIONS_FOR_A_DIRECTION == 3


def test_two_observations_still_establish_whether_it_persisted():
    """Persistence is a different question from direction, and needs less."""
    series = _egfr([48.0, 44.0]).series_for("egfr")
    assert series.trend is Trend.INSUFFICIENT
    assert series.persistence is Persistence.PERSISTENT


# --- persistence ----------------------------------------------------
def test_abnormal_at_both_ends_is_persistent():
    series = _egfr([52.0, 49.0, 46.0]).series_for("egfr")
    assert series.persistence is Persistence.PERSISTENT
    assert series.abnormal_in_direction(ReferenceStatus.BELOW)


def test_abnormal_then_normal_is_transient():
    series = _egfr([52.0, 78.0, 91.0]).series_for("egfr")
    assert series.persistence is Persistence.TRANSIENT
    assert not series.abnormal_in_direction(ReferenceStatus.BELOW)


def test_normal_then_abnormal_is_new_rather_than_persistent():
    series = _egfr([92.0, 84.0, 52.0]).series_for("egfr")
    assert series.persistence is Persistence.NEW
    assert not series.abnormal_in_direction(ReferenceStatus.BELOW)


def test_normal_throughout_is_never_abnormal():
    series = _egfr([92.0, 88.0, 90.0]).series_for("egfr")
    assert series.persistence is Persistence.NEVER_ABNORMAL


def test_one_observation_establishes_nothing():
    series = _egfr([52.0]).series_for("egfr")
    assert series.persistence is Persistence.NOT_ESTABLISHED
    assert series.trend is Trend.INSUFFICIENT


# --- what a series refuses to be built from -------------------------
def test_two_laboratories_using_different_units_still_form_one_series():
    """The trend is plotted in the canonical unit. Refusing to put g/dL and
    g/L together would lose the history rather than report it."""
    history = build_history([
        ReportSnapshot("r-0", START,
                       [_record("Hemoglobin", 13.4, "g/dL", "13.0 - 17.0")]),
        ReportSnapshot("r-1", START + timedelta(days=120),
                       [_record("Hemoglobin", 11.8, "g/dL", "13.0 - 17.0")]),
        ReportSnapshot("r-2", START + timedelta(days=240),
                       [_record("Hemoglobin", 104.0, "g/L", "130 - 175")]),
    ], sex="male")
    series = history.series_for("hemoglobin")

    assert series is not None
    assert series.unit == "g/L"
    assert [o.value for o in series.observations] == [134.0, 118.0, 104.0]
    assert series.trend is Trend.FALLING


def test_the_reference_status_still_comes_from_each_laboratorys_own_range():
    """Trending in one unit and comparing in another is deliberate: they
    answer different questions."""
    history = build_history([
        ReportSnapshot("r-0", START,
                       [_record("Hemoglobin", 13.4, "g/dL", "13.0 - 17.0")]),
        ReportSnapshot("r-1", START + timedelta(days=120),
                       [_record("Hemoglobin", 104.0, "g/L", "130 - 175")]),
    ], sex="male")
    series = history.series_for("hemoglobin")

    assert series.earliest.status is ReferenceStatus.WITHIN
    assert series.latest.status is ReferenceStatus.BELOW
    assert series.persistence is Persistence.NEW


def test_values_that_cannot_be_brought_to_one_scale_are_named_not_dropped():
    """A series that quietly goes missing is worse than one that says which
    analyte it could not build."""
    from intelligence.findings.history import build_series

    mixed = [
        Observation(analyte="mystery", value=1.0, unit="widgets",
                    observed_on=START, status=ReferenceStatus.UNKNOWN,
                    report_id="r-0"),
        Observation(analyte="mystery", value=2.0, unit="sprockets",
                    observed_on=START + timedelta(days=90),
                    status=ReferenceStatus.UNKNOWN, report_id="r-1"),
    ]
    assert build_series("mystery", mixed) is None


def test_a_changed_reference_range_is_carried_as_a_caveat():
    """'Was abnormal, now normal' may be the range moving, not the patient."""
    history = build_history([
        ReportSnapshot("r-0", START,
                       [_record("SGPT", 44.0, "U/L", "0 - 40")]),
        ReportSnapshot("r-1", START + timedelta(days=120),
                       [_record("SGPT", 44.0, "U/L", "0 - 50")]),
    ])
    series = history.series_for("alt")
    assert any("reference range printed against this test changed" in c
               for c in series.caveats)


def test_an_egfr_series_always_warns_about_the_equation():
    series = _egfr([92.0, 84.0, 71.0]).series_for("egfr")
    assert any("different equations" in c for c in series.caveats)


def test_a_result_with_no_range_is_counted_as_not_contributing():
    history = build_history([
        ReportSnapshot("r-0", START, [_record("eGFR", 52.0, "mL/min/1.73m2")]),
        ReportSnapshot("r-1", START + timedelta(days=120),
                       [_record("eGFR", 49.0, "mL/min/1.73m2", "> 60")]),
    ])
    series = history.series_for("egfr")
    assert series is not None
    assert series.count == 2


# --- what the assembled set declares it holds -----------------------
def test_one_report_declares_only_a_single_report_timeline():
    history = build_history(_snapshots("eGFR", "mL/min/1.73m2", "> 60", [52.0]))
    evidence = history.evidence
    assert evidence.supports(EvidenceTemporality.SINGLE_REPORT)
    assert not evidence.supports(EvidenceTemporality.HISTORICAL)


def test_several_reports_declare_the_timeline_they_actually_carry():
    evidence = _egfr([92.0, 84.0, 71.0]).evidence
    for temporality in EvidenceTemporality:
        assert evidence.supports(temporality), temporality
    assert evidence.observation_window_days == 240.0


def test_the_latest_report_supplies_the_measurements_detectors_read():
    """So every existing single-report detector behaves exactly as before."""
    evidence = _egfr([92.0, 84.0, 46.0]).evidence
    assert evidence.measurement("egfr").value == 46.0


def test_no_snapshots_gives_an_empty_set_rather_than_an_error():
    history = build_history([])
    assert history.reports == 0
    assert history.evidence.measurements == {}


# --- and the condition detector that finally has what it needs ------
def _ckd(values, *, every_days=120):
    history = _egfr(values, every_days=every_days)
    report = detect(history.evidence)
    return next(
        f for f in report.findings if f.code == "POSSIBLE_CHRONIC_KIDNEY_DISEASE"
    )


def test_a_sustained_low_egfr_across_ninety_days_finally_reaches_provisional():
    finding = _ckd([52.0, 49.0, 46.0])
    assert finding.confidence is Confidence.PROVISIONAL
    assert any("already outside its range" in c for c in finding.caveats)
    assert any("Acute-on-chronic" in c for c in finding.caveats)


def test_it_still_never_exceeds_provisional():
    assert _ckd([52.0, 49.0, 46.0]).confidence is not Confidence.SUPPORTED


def test_a_new_abnormality_across_a_long_window_is_not_chronic():
    """The window is long; the abnormality is not. This is the case that
    separates chronic kidney disease from an acute injury."""
    finding = _ckd([92.0, 88.0, 46.0])
    assert finding.confidence is Confidence.INSUFFICIENT
    assert any("new rather than persistent" in m
               for m in finding.evidence_missing)


def test_an_abnormality_that_recovered_is_not_chronic_either():
    history = _egfr([46.0, 72.0, 91.0])
    report = detect(history.evidence)
    # The latest eGFR is normal, so there is no entry criterion at all and the
    # detector is silent rather than insufficient.
    assert not any(
        f.code == "POSSIBLE_CHRONIC_KIDNEY_DISEASE" for f in report.findings
    )


def test_a_sustained_abnormality_over_too_short_a_window_is_not_chronic():
    finding = _ckd([52.0, 49.0, 46.0], every_days=20)
    assert finding.confidence is Confidence.INSUFFICIENT
    assert any("further" in m and "days" in m for m in finding.evidence_missing)


@pytest.mark.parametrize("values", [
    [52.0, 49.0, 46.0],
    [92.0, 88.0, 46.0],
    [52.0, 78.0, 46.0],
])
def test_the_finding_always_needs_a_human_whatever_the_history(values):
    assert _ckd(values).human_review_required is True
