"""Evidence assembly and detector behaviour.

The clinically important cases here are the negative ones: what happens when a
value did not survive validation, when the report printed no reference range,
and when a level-3 detector has the anaemia but not the indices that would
explain it.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import ReferenceStatus, TextSource, ValueStatus
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.provenance import build_provenance
from intelligence.document.validation import validate_value
from intelligence.findings import (
    Confidence,
    EvidenceLevel,
    EvidenceSet,
    Measurement,
    build_evidence,
    detect,
)
from intelligence.findings.hematology import ANEMIA, EOSINOPHILIA
from intelligence.findings.metabolic import DYSLIPIDEMIA


def _evidence_with(*measurements) -> EvidenceSet:
    """An EvidenceSet built by hand, for branches a real report cannot reach."""
    return EvidenceSet(measurements={m.analyte: m for m in measurements})


class _Record:
    def __init__(self, value, provenance=None):
        self.value = value
        self.provenance = provenance


def _raw(label, value, unit, ref="", flag=""):
    return RawExtraction(
        label=label, value_text=str(value), value=value, unit=unit,
        reference_text=ref, printed_flag=flag,
        line=f"{label} {value} {unit} {ref}".strip(),
        page=1, char_span=(0, 20), extraction_confidence=0.85,
    )


def _record(label, value, unit, ref="", flag="", schema=None):
    raw = _raw(label, value, unit, ref, flag)
    validated = validate_value(raw, schema=schema)
    provenance = build_provenance(
        raw, source_sha256="sha", text_source=TextSource.EMBEDDED_TEXT_LAYER,
        section="COMPLETE BLOOD COUNT",
    )
    return _Record(validated, provenance)


# --- only validated values become evidence --------------------------
def test_a_value_that_failed_validation_is_never_evidence():
    """A number nobody trusted must not end up under a finding."""
    bad = _record("Hemoglobin", 9.8, "parsecs", "13.0 - 17.0")
    assert bad.value.status is not ValueStatus.OBSERVED

    evidence = build_evidence([bad])
    assert evidence.measurement("hemoglobin") is None
    assert "hemoglobin" in evidence.unusable
    assert ANEMIA.evaluate(evidence) is None


def test_an_observed_value_becomes_a_measurement_with_its_provenance():
    evidence = build_evidence([_record("Hemoglobin", 9.8, "g/dL", "13.0 - 17.0")])
    measurement = evidence.measurement("hemoglobin")

    assert measurement.status is ReferenceStatus.BELOW
    assert measurement.reference_source == "report"
    ref = measurement.to_ref()
    assert ref.page == 1
    assert ref.section == "COMPLETE BLOOD COUNT"
    assert ref.source_text


# --- the laboratory's own range wins --------------------------------
def test_the_printed_range_is_preferred_over_the_fallback_table():
    # A deliberately odd printed range: if the fallback were used, 9.8 g/dL
    # would read as low. The lab said otherwise, and the lab wins.
    evidence = build_evidence([_record("Hemoglobin", 9.8, "g/dL", "9.0 - 12.0")])
    measurement = evidence.measurement("hemoglobin")

    assert measurement.reference_source == "report"
    assert measurement.status is ReferenceStatus.WITHIN
    assert ANEMIA.evaluate(evidence) is None


def test_the_fallback_table_is_used_when_the_report_prints_nothing():
    evidence = build_evidence([_record("Hemoglobin", 9.8, "g/dL")], sex="male")
    measurement = evidence.measurement("hemoglobin")

    assert measurement.reference_source == "fallback-table"
    assert measurement.unit == "g/L" and measurement.value == 98.0
    finding = ANEMIA.evaluate(evidence)
    assert finding.confidence is Confidence.PROVISIONAL
    assert any("did not print a reference range" in c for c in finding.caveats)


def test_an_unknown_sex_widens_the_interval_and_says_so():
    evidence = build_evidence([_record("Hemoglobin", 125.0, "g/L")])
    measurement = evidence.measurement("hemoglobin")
    assert measurement.reference_low == 120.0     # the wider, male-inclusive floor
    assert any("sex not known" in c for c in [measurement.reference_note])


def test_an_absolute_eosinophil_count_is_never_read_against_the_percentage_range():
    """The exclusion rule, made structural.

    A percentage and an absolute count are different measurements. There is
    deliberately no conversion rule for an absolute eosinophil count, so it
    fails validation at the document stage and never becomes evidence - rather
    than being compared against a 1-6 *percent* interval and called
    eosinophilia at 9.2 x10^9/L.
    """
    record = _record("Eosinophils", 9.2, "10^9/L")
    assert record.value.status is ValueStatus.NEEDS_REVIEW

    evidence = build_evidence([record])
    assert evidence.measurement("eosinophils") is None
    assert "eosinophils" in evidence.unusable
    assert EOSINOPHILIA.evaluate(evidence) is None


def test_a_measurement_with_no_comparable_range_yields_an_insufficient_finding():
    """Applicable but unanswerable is not the same as nothing to say."""
    evidence = _evidence_with(
        Measurement(
            analyte="eosinophils", value=9.2, unit="%", reference_low=None,
            reference_high=None, reference_text="", reference_source="none",
            reference_kind="", status=ReferenceStatus.UNKNOWN,
        )
    )
    finding = EOSINOPHILIA.evaluate(evidence)

    assert finding is not None
    assert finding.confidence is Confidence.INSUFFICIENT
    assert finding.evidence_missing
    assert not finding.asserts_anything


def test_a_detector_whose_analyte_is_absent_stays_silent():
    """Not applicable is silence, not an 'insufficient evidence' notice."""
    evidence = build_evidence([_record("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0")])
    assert EOSINOPHILIA.evaluate(evidence) is None


# --- level 2 behaviour ---------------------------------------------
def test_a_low_haemoglobin_gives_a_supported_anaemia_pattern():
    evidence = build_evidence([_record("Hemoglobin", 9.8, "g/dL", "13.0 - 17.0", "L")])
    finding = ANEMIA.evaluate(evidence)

    assert finding.code == "ANEMIA_PATTERN"
    assert finding.level is EvidenceLevel.CLINICAL_ABNORMALITY
    assert finding.confidence is Confidence.SUPPORTED
    assert finding.human_review_required is True
    assert finding.explanation and "doctor" in finding.explanation.lower()


def test_a_normal_value_produces_no_finding():
    evidence = build_evidence([_record("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0")])
    assert ANEMIA.evaluate(evidence) is None


def test_a_decision_threshold_can_never_be_more_than_provisional():
    """Above a treatment target is not the same as abnormal."""
    evidence = build_evidence([_record("LDL Cholesterol", 4.2, "mmol/L")])
    finding = DYSLIPIDEMIA.evaluate(evidence)

    assert finding.confidence is Confidence.PROVISIONAL
    assert any("treatment target" in c for c in finding.caveats)


def test_dyslipidemia_fires_on_any_one_lipid():
    evidence = build_evidence([
        _record("Total Cholesterol", 4.4, "mmol/L", "0.0 - 5.2"),
        _record("HDL Cholesterol", 0.7, "mmol/L", "1.0 - 2.0"),
    ])
    finding = DYSLIPIDEMIA.evaluate(evidence)
    assert finding is not None
    assert any("hdl" in c for c in finding.caveats)


def test_dyslipidemia_stays_silent_on_a_non_lipid_report():
    evidence = build_evidence([_record("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0")])
    assert DYSLIPIDEMIA.evaluate(evidence) is None


# --- level 3: the whole point of the level boundary ----------------
def _cbc(hb=9.8, mcv=None, ferritin=None):
    records = [_record("Hemoglobin", hb, "g/dL", "13.0 - 17.0")]
    if mcv is not None:
        records.append(_record("MCV", mcv, "fL", "80 - 100"))
    if ferritin is not None:
        records.append(_record("Ferritin", ferritin, "ng/mL", "30 - 400"))
    return build_evidence(records, sex="male")


def test_haemoglobin_alone_never_reaches_iron_deficiency():
    report = detect(_cbc())
    iron = next(f for f in report.findings if f.code == "POSSIBLE_IRON_DEFICIENCY_ANEMIA")

    assert iron.confidence is Confidence.INSUFFICIENT
    assert not iron.asserts_anything
    assert set(iron.evidence_missing) == {"mcv", "ferritin"}


def test_a_low_mcv_makes_it_provisional_and_names_the_missing_ferritin():
    report = detect(_cbc(mcv=72.0))
    iron = next(f for f in report.findings if f.code == "POSSIBLE_IRON_DEFICIENCY_ANEMIA")

    assert iron.confidence is Confidence.PROVISIONAL
    assert iron.evidence_missing == ["ferritin"]
    assert any("thalassaemia" in c.lower() for c in iron.caveats)


def test_a_low_ferritin_makes_it_supported():
    report = detect(_cbc(mcv=72.0, ferritin=8.0))
    iron = next(f for f in report.findings if f.code == "POSSIBLE_IRON_DEFICIENCY_ANEMIA")

    assert iron.confidence is Confidence.SUPPORTED
    assert iron.evidence_missing == []
    assert {e.key for e in iron.evidence_used} >= {
        "ANEMIA_PATTERN", "MICROCYTOSIS_PATTERN", "ferritin"
    }


def test_no_anaemia_means_the_iron_detector_says_nothing_at_all():
    evidence = build_evidence([
        _record("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0"),
        _record("MCV", 72.0, "fL", "80 - 100"),
    ])
    report = detect(evidence)
    assert not any(
        f.code == "POSSIBLE_IRON_DEFICIENCY_ANEMIA" for f in report.findings
    )


# --- the engine -----------------------------------------------------
def test_level_2_runs_before_level_3_reads_it():
    report = detect(_cbc(mcv=72.0))
    levels = [f.level.value for f in report.findings]
    assert levels == sorted(levels, reverse=True)   # reported highest-first
    iron = next(f for f in report.findings if f.level is EvidenceLevel.CONDITION_LIKELIHOOD)
    assert any(e.key == "ANEMIA_PATTERN" for e in iron.evidence_used)


def test_an_insufficient_finding_is_never_built_upon():
    """'I cannot tell' is a statement about the report, not a fact."""
    evidence = _evidence_with(
        Measurement(
            analyte="eosinophils", value=9.2, unit="%", reference_low=None,
            reference_high=None, reference_text="", reference_source="none",
            reference_kind="", status=ReferenceStatus.UNKNOWN,
        )
    )
    report = detect(evidence)
    insufficient = [f for f in report.findings if not f.asserts_anything]
    assert insufficient
    for finding in insufficient:
        assert finding.code not in evidence.findings


def test_the_report_flags_that_a_human_must_look():
    report = detect(_cbc(mcv=72.0))
    assert report.needs_human_review is True
    assert report.highest_level is EvidenceLevel.CONDITION_LIKELIHOOD


def test_findings_carry_the_versions_they_were_produced_with():
    report = detect(_cbc(mcv=72.0))
    assert report.range_table_version
    for finding in report.findings:
        assert ":" in finding.detector       # code:version


@pytest.mark.parametrize("value,expected", [(9.8, True), (14.0, False)])
def test_anaemia_detection_is_deterministic(value, expected):
    first = detect(_cbc(hb=value))
    second = detect(_cbc(hb=value))
    codes = lambda r: sorted(f.code for f in r.findings if f.asserts_anything)  # noqa: E731
    assert codes(first) == codes(second)
    assert ("ANEMIA_PATTERN" in codes(first)) is expected
