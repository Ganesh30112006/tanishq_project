"""Level 3: the conditions, and above all what they refuse to conclude.

Every test here is about a boundary rather than a happy path. A level-3
detector that fires is only useful if the same detector reliably does *not*
fire when the evidence is thin, because the two results look identical to a
reader who was not told which one they got.

The chronic kidney disease detector is the clearest case in the system. It
will not assert anything from a single report, no matter how bad the numbers
are, because the word in its name is *chronic* and one report cannot establish
chronicity. Today that means it never fires. That is the correct answer.
"""
from __future__ import annotations

import pytest

from intelligence.disease.hepatic import CHOLESTATIC, HEPATOCELLULAR
from intelligence.disease.renal import CHRONIC_KIDNEY_DISEASE
from intelligence.disease.renal.chronic_kidney_disease import CHRONICITY_DAYS
from intelligence.disease.thyroid import (
    PRIMARY_HYPOTHYROIDISM,
    SUBCLINICAL_HYPOTHYROIDISM,
)
from intelligence.document.contracts import TextSource
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.provenance import build_provenance
from intelligence.document.validation import validate_value
from intelligence.findings import registry
from intelligence.findings.contracts import (
    Confidence,
    EvidenceLevel,
    EvidenceTemporality,
)
from intelligence.findings.engine import detect
from intelligence.findings.evidence import build_evidence
from intelligence.knowledge import findings as KB


class _Record:
    def __init__(self, value, provenance=None):
        self.value = value
        self.provenance = provenance


def _record(label, value, unit, ref="", flag=""):
    raw = RawExtraction(
        label=label, value_text=str(value), value=value, unit=unit,
        reference_text=ref, printed_flag=flag,
        line=f"{label} {value} {unit} {ref}".strip(),
        page=1, char_span=(0, 20), extraction_confidence=0.85,
    )
    return _Record(
        validate_value(raw),
        build_provenance(raw, source_sha256="sha",
                         text_source=TextSource.EMBEDDED_TEXT_LAYER,
                         section="PANEL"),
    )


def _evidence(*rows, sex=None):
    return build_evidence([_record(*row) for row in rows], sex=sex)


def _find(report, code):
    return next((f for f in report.findings if f.code == code), None)


# --- chronic kidney disease: the timeline gate doing real work ------
RENAL = (
    ("S. Creatinine", 2.1, "mg/dL", "0.6 - 1.2"),
    ("eGFR", 38.0, "mL/min/1.73m2"),
    ("ACR", 120.0, "mg/g"),
)


def test_chronic_kidney_disease_is_never_asserted_from_one_report():
    """However bad the numbers are. Acute kidney injury produces exactly
    these, and it recovers."""
    finding = _find(detect(_evidence(*RENAL, sex="male")),
                    "POSSIBLE_CHRONIC_KIDNEY_DISEASE")

    assert finding is not None
    assert finding.confidence is Confidence.INSUFFICIENT
    assert not finding.asserts_anything
    assert any(str(CHRONICITY_DAYS) in m for m in finding.evidence_missing)


def test_it_names_the_repeat_it_wanted_rather_than_a_generic_requirement():
    finding = _find(detect(_evidence(*RENAL, sex="male")),
                    "POSSIBLE_CHRONIC_KIDNEY_DISEASE")
    missing = " ".join(finding.evidence_missing)
    assert "earlier" in missing
    assert any("not the same as chronic kidney disease" in c
               for c in finding.caveats)


def test_it_stays_silent_when_neither_entry_criterion_is_present():
    """Silence, not an 'insufficient evidence' notice on a normal panel."""
    normal = _evidence(("S. Creatinine", 0.9, "mg/dL", "0.6 - 1.2"), sex="male")
    assert CHRONIC_KIDNEY_DISEASE.evaluate(normal) is None


def test_it_becomes_provisional_and_never_more_once_the_history_exists():
    evidence = _evidence(*RENAL, sex="male")
    detect(evidence)                       # level 2 first, as the engine does
    evidence.available_temporality = frozenset({
        EvidenceTemporality.SINGLE_REPORT,
        EvidenceTemporality.REPEATED_MEASUREMENT,
        EvidenceTemporality.HISTORICAL,
    })
    evidence.observation_window_days = 200.0

    finding = CHRONIC_KIDNEY_DISEASE.evaluate(evidence)
    assert finding.confidence is Confidence.PROVISIONAL
    assert any("Acute-on-chronic" in c for c in finding.caveats)


def test_a_history_shorter_than_the_criterion_is_still_not_enough():
    evidence = _evidence(*RENAL, sex="male")
    detect(evidence)
    evidence.available_temporality = frozenset({
        EvidenceTemporality.SINGLE_REPORT, EvidenceTemporality.HISTORICAL,
    })
    evidence.observation_window_days = 40.0

    finding = CHRONIC_KIDNEY_DISEASE.evaluate(evidence)
    assert finding.confidence is Confidence.INSUFFICIENT
    assert any("further 50 days" in m for m in finding.evidence_missing)


def test_it_never_offers_a_stage():
    joined = " ".join(KB.get("POSSIBLE_CHRONIC_KIDNEY_DISEASE").must_not_say).lower()
    assert "stage" in joined
    assert "dialysis" in joined


# --- hypothyroidism: two patterns that need the free T4 to separate --
def test_a_raised_tsh_with_a_low_free_t4_reaches_the_overt_pattern():
    report = detect(_evidence(
        ("TSH", 9.1, "uIU/mL", "0.4 - 4.0"),
        ("Free T4", 0.6, "ng/dL", "0.8 - 1.8"),
    ))
    overt = _find(report, "POSSIBLE_PRIMARY_HYPOTHYROIDISM")
    assert overt.confidence is Confidence.PROVISIONAL
    assert _find(report, "POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM") is None


def test_a_raised_tsh_with_a_normal_free_t4_reaches_the_subclinical_one():
    """The normal free T4 is required evidence, not an absence."""
    report = detect(_evidence(
        ("TSH", 6.2, "uIU/mL", "0.4 - 4.0"),
        ("Free T4", 1.3, "ng/dL", "0.8 - 1.8"),
    ))
    subclinical = _find(report, "POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM")
    assert subclinical.confidence is Confidence.PROVISIONAL
    assert _find(report, "POSSIBLE_PRIMARY_HYPOTHYROIDISM") is None


def test_a_raised_tsh_alone_cannot_tell_the_two_apart():
    report = detect(_evidence(("TSH", 9.1, "uIU/mL", "0.4 - 4.0")))
    for code in ("POSSIBLE_PRIMARY_HYPOTHYROIDISM",
                 "POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM"):
        finding = _find(report, code)
        assert finding.confidence is Confidence.INSUFFICIENT
        assert finding.evidence_missing == ["a free T4 with a reference interval"]


def test_neither_thyroid_condition_fires_without_a_raised_tsh():
    normal = _evidence(
        ("TSH", 2.1, "uIU/mL", "0.4 - 4.0"),
        ("Free T4", 1.3, "ng/dL", "0.8 - 1.8"),
    )
    detect(normal)
    assert PRIMARY_HYPOTHYROIDISM.evaluate(normal) is None
    assert SUBCLINICAL_HYPOTHYROIDISM.evaluate(normal) is None


def test_neither_thyroid_condition_can_ever_be_supported():
    """A repeat sample is required before either means anything, and acute
    illness - invisible on a report - produces both."""
    for detector in (PRIMARY_HYPOTHYROIDISM, SUBCLINICAL_HYPOTHYROIDISM):
        assert "never SUPPORTED" in detector.contract.confidence_policy

    report = detect(_evidence(
        ("TSH", 9.1, "uIU/mL", "0.4 - 4.0"),
        ("Free T4", 0.6, "ng/dL", "0.8 - 1.8"),
    ))
    overt = _find(report, "POSSIBLE_PRIMARY_HYPOTHYROIDISM")
    assert overt.confidence is not Confidence.SUPPORTED
    assert any("second sample" in c for c in overt.caveats)


# --- the liver shape: a comparison, never one raised enzyme ---------
def test_a_hepatocellular_shape_needs_both_enzymes_not_one():
    only_alt = _evidence(("SGPT", 320.0, "U/L", "0 - 40"))
    detect(only_alt)
    finding = HEPATOCELLULAR.evaluate(only_alt)
    assert finding.confidence is Confidence.INSUFFICIENT
    assert "alp" in finding.evidence_missing


def test_a_high_r_ratio_gives_the_hepatocellular_shape():
    report = detect(_evidence(
        ("SGPT", 320.0, "U/L", "0 - 40"),
        ("Alkaline Phosphatase", 110.0, "U/L", "30 - 120"),
    ))
    finding = _find(report, "PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY")
    assert finding.confidence is Confidence.PROVISIONAL
    assert any("R ratio" in c for c in finding.caveats)
    assert _find(report, "PATTERN_SUGGESTIVE_OF_CHOLESTASIS") is None
    # A GGT is only material to the cholestatic reading.
    assert finding.evidence_missing == []


def test_a_low_r_ratio_gives_the_cholestatic_shape_and_asks_for_a_ggt():
    report = detect(_evidence(
        ("SGPT", 44.0, "U/L", "0 - 40"),
        ("Alkaline Phosphatase", 420.0, "U/L", "30 - 120"),
    ))
    finding = _find(report, "PATTERN_SUGGESTIVE_OF_CHOLESTASIS")
    assert finding.confidence is Confidence.PROVISIONAL
    assert finding.evidence_missing == ["ggt"]
    assert any("bone source" in c for c in finding.caveats)


def test_a_middling_ratio_is_named_as_mixed_rather_than_forced():
    """ALT at 4x its limit and ALP at 1.3x gives R = 3.0, between the two
    conventional boundaries. Both enzymes are raised, so both detectors are
    applicable, and neither is allowed to claim the shape."""
    report = detect(_evidence(
        ("SGPT", 160.0, "U/L", "0 - 40"),
        ("Alkaline Phosphatase", 160.0, "U/L", "30 - 120"),
    ))
    for code in ("PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY",
                 "PATTERN_SUGGESTIVE_OF_CHOLESTASIS"):
        finding = _find(report, code)
        assert finding is not None, code
        assert finding.confidence is Confidence.INSUFFICIENT
        assert any("mixed picture" in c for c in finding.caveats)


def test_a_normal_liver_panel_produces_no_shape_at_all():
    normal = _evidence(
        ("SGPT", 22.0, "U/L", "0 - 40"),
        ("Alkaline Phosphatase", 80.0, "U/L", "30 - 120"),
    )
    detect(normal)
    assert HEPATOCELLULAR.evaluate(normal) is None
    assert CHOLESTATIC.evaluate(normal) is None


def test_neither_liver_shape_may_name_a_disease():
    for code in ("PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY",
                 "PATTERN_SUGGESTIVE_OF_CHOLESTASIS"):
        joined = " ".join(KB.get(code).must_not_say).lower()
        assert "liver disease" in joined


# --- what every level-3 detector has in common ----------------------
def test_every_level_3_detector_is_hedged_reviewed_and_unvalidated():
    for detector in registry.by_level(EvidenceLevel.CONDITION_LIKELIHOOD):
        contract = detector.contract
        assert contract.code.startswith(
            ("POSSIBLE_", "SUSPECTED_", "PATTERN_SUGGESTIVE_OF_")
        ), contract.code
        assert contract.human_review_required
        assert len(contract.required_evidence) + len(contract.optional_evidence) >= 2
        assert KB.get(contract.code).must_not_say


@pytest.mark.parametrize(
    "detector",
    registry.by_level(EvidenceLevel.CONDITION_LIKELIHOOD),
    ids=lambda d: d.contract.code,
)
def test_no_level_3_detector_speaks_on_an_unrelated_report(detector):
    unrelated = _evidence(("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0"))
    detect(unrelated)
    assert detector.evaluate(unrelated) is None
