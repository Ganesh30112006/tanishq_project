"""The renal, hepatic, thyroid and electrolyte patterns.

The behaviour worth pinning is not that a high number produces a finding -
that is one comparison. It is what the findings refuse to become: separate
enzyme findings rather than one "deranged liver function", a low eGFR that
stays a low eGFR, an electrolyte result that carries the artefact most likely
to have faked it, and silence rather than noise on a panel that does not
contain the analyte at all.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import TextSource
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.provenance import build_provenance
from intelligence.document.validation import validate_value
from intelligence.findings import registry
from intelligence.findings.contracts import Confidence, EvidenceLevel
from intelligence.findings.electrolytes import (
    HYPERKALEMIA,
    HYPOCALCEMIA,
    HYPONATREMIA,
    LOW_BICARBONATE,
)
from intelligence.findings.engine import detect
from intelligence.findings.evidence import build_evidence
from intelligence.findings.hematology import RDW_ELEVATION
from intelligence.findings.hepatic import ALT_ELEVATION, AST_ELEVATION, LOW_ALBUMIN
from intelligence.findings.renal import (
    ALBUMINURIA,
    CREATININE_ELEVATION,
    REDUCED_EGFR,
    UREA_ELEVATION,
)
from intelligence.findings.thyroid import TSH_ELEVATION, TSH_SUPPRESSION
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


# --- renal ----------------------------------------------------------
def test_a_raised_creatinine_is_a_raised_creatinine_and_nothing_more():
    finding = CREATININE_ELEVATION.evaluate(
        _evidence(("S. Creatinine", 1.6, "mg/dL", "0.6 - 1.2"))
    )
    assert finding.code == "CREATININE_ELEVATION_PATTERN"
    assert finding.level is EvidenceLevel.CLINICAL_ABNORMALITY
    assert finding.confidence is Confidence.SUPPORTED
    entry = KB.get(finding.code)
    assert any("kidney disease" in rule for rule in entry.must_not_say)


def test_a_normal_creatinine_produces_nothing():
    assert CREATININE_ELEVATION.evaluate(
        _evidence(("S. Creatinine", 0.9, "mg/dL", "0.6 - 1.2"))
    ) is None


def test_a_low_egfr_against_a_staging_boundary_can_never_exceed_provisional():
    """Below 60 is a guideline boundary, not an abnormality boundary, and the
    finding has to say so rather than leave a reader to infer it."""
    finding = REDUCED_EGFR.evaluate(_evidence(("eGFR", 46.0, "mL/min/1.73m2")))
    assert finding.confidence is Confidence.PROVISIONAL
    assert any("treatment target" in c or "reference range" in c
               for c in finding.caveats)


def test_a_low_egfr_never_names_chronic_kidney_disease():
    entry = KB.get("REDUCED_EGFR_PATTERN")
    joined = " ".join(entry.must_not_say).lower()
    assert "chronic kidney disease" in joined
    assert "ninety days" in joined


def test_urea_fires_from_either_urea_or_blood_urea_nitrogen():
    """Two analytes because the mg/dL factors differ; one pattern because the
    clinical observation is the same."""
    from_urea = UREA_ELEVATION.evaluate(
        _evidence(("Blood Urea", 58.0, "mg/dL", "15 - 40"))
    )
    from_bun = UREA_ELEVATION.evaluate(
        _evidence(("Blood Urea Nitrogen", 27.0, "mg/dL", "7 - 20"))
    )
    assert from_urea.code == from_bun.code == "UREA_ELEVATION_PATTERN"
    assert UREA_ELEVATION.contract.required_evidence_mode == "any"


def test_a_raised_urine_ratio_is_not_called_persistent_albuminuria():
    finding = ALBUMINURIA.evaluate(
        _evidence(("ACR", 85.0, "mg/g"))
    )
    assert finding is not None
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "damaged" in joined


# --- hepatic --------------------------------------------------------
def test_each_raised_enzyme_is_its_own_finding():
    """Which enzymes rose together is the whole of the information. One
    'abnormal liver function' finding would discard it."""
    evidence = _evidence(
        ("SGPT (ALT)", 78.0, "U/L", "0 - 40"),
        ("SGOT (AST)", 64.0, "U/L", "0 - 40"),
    )
    codes = {f.code for f in detect(evidence).findings}
    assert {"ALT_ELEVATION_PATTERN", "AST_ELEVATION_PATTERN"} <= codes
    assert not any("DERANGED" in c or "ABNORMAL_LFT" in c for c in codes)


def test_a_raised_alt_never_mentions_alcohol_or_names_a_liver_disease():
    finding = ALT_ELEVATION.evaluate(_evidence(("SGPT", 78.0, "U/L", "0 - 40")))
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "drinks too much" in joined
    assert "liver disease" in joined


def test_a_raised_ast_says_it_is_not_only_a_liver_enzyme():
    finding = AST_ELEVATION.evaluate(_evidence(("SGOT", 64.0, "U/L", "0 - 40")))
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "muscle" in joined


def test_a_low_albumin_is_not_called_malnutrition():
    finding = LOW_ALBUMIN.evaluate(
        _evidence(("Serum Albumin", 3.1, "g/dL", "3.5 - 5.0"))
    )
    assert finding.confidence is Confidence.SUPPORTED
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "malnourished" in joined


# --- thyroid --------------------------------------------------------
def test_tsh_high_and_tsh_low_are_mutually_exclusive():
    high = _evidence(("TSH", 8.4, "uIU/mL", "0.4 - 4.0"))
    assert TSH_ELEVATION.evaluate(high) is not None
    assert TSH_SUPPRESSION.evaluate(high) is None

    low = _evidence(("TSH", 0.05, "uIU/mL", "0.4 - 4.0"))
    assert TSH_ELEVATION.evaluate(low) is None
    assert TSH_SUPPRESSION.evaluate(low) is not None


def test_a_thyroid_panel_produces_separate_level_2_findings():
    """A raised TSH with a low free T4 is a recognisable pattern, and reading
    the two together is a level-3 conclusion this level may not reach. Level 2
    reports each number against its own range and stops there."""
    evidence = _evidence(
        ("TSH", 8.4, "uIU/mL", "0.4 - 4.0"),
        ("Free T4", 0.7, "ng/dL", "0.8 - 1.8"),
    )
    findings = detect(evidence).findings
    level_2 = {
        f.code for f in findings if f.level is EvidenceLevel.CLINICAL_ABNORMALITY
    }
    assert level_2 == {"TSH_ELEVATION_PATTERN", "LOW_FREE_T4_PATTERN"}
    for code in level_2:
        joined = " ".join(KB.get(code).must_not_say).lower()
        assert "thyroid condition" in joined or "hypothyroidism" in joined


def test_every_thyroid_finding_warns_that_illness_makes_it_unreliable():
    for code in ("TSH_ELEVATION_PATTERN", "TSH_SUPPRESSION_PATTERN",
                 "LOW_FREE_T4_PATTERN", "HIGH_FREE_T4_PATTERN"):
        notes = " ".join(KB.get(code).cautionary_notes).lower()
        assert "illness" in notes, code


# --- electrolytes ---------------------------------------------------
def test_a_raised_potassium_carries_the_artefact_that_most_often_fakes_it():
    finding = HYPERKALEMIA.evaluate(
        _evidence(("Serum Potassium", 5.8, "mmol/L", "3.5 - 5.1"))
    )
    assert finding.confidence is Confidence.SUPPORTED
    notes = " ".join(finding.caveats).lower()
    assert "haemolysis" in notes


def test_no_electrolyte_finding_tells_the_patient_about_their_heart():
    """Frightening, not established by a number, and the doctor's to raise."""
    for code in ("HYPOKALEMIA_PATTERN", "HYPERKALEMIA_PATTERN"):
        joined = " ".join(KB.get(code).must_not_say).lower()
        assert "heart" in joined, code


def test_a_low_calcium_says_it_may_be_the_albumin():
    finding = HYPOCALCEMIA.evaluate(
        _evidence(("Serum Calcium", 8.2, "mg/dL", "8.6 - 10.2"))
    )
    notes = (" ".join(finding.caveats) + " "
             + " ".join(KB.get(finding.code).cautionary_notes)).lower()
    assert "albumin" in notes


def test_a_low_bicarbonate_never_says_acidosis():
    finding = LOW_BICARBONATE.evaluate(
        _evidence(("Bicarbonate", 18.0, "mmol/L", "22 - 29"))
    )
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "acidosis" in joined


def test_a_sodium_inside_its_range_produces_no_finding():
    assert HYPONATREMIA.evaluate(
        _evidence(("Serum Sodium", 140.0, "mmol/L", "136 - 145"))
    ) is None


# --- haematology ----------------------------------------------------
def test_a_raised_rdw_asserts_the_index_and_not_a_cause():
    finding = RDW_ELEVATION.evaluate(_evidence(("RDW-CV", 17.2, "%", "11.5 - 14.5")))
    assert finding.code == "RDW_ELEVATION_PATTERN"
    joined = " ".join(KB.get(finding.code).must_not_say).lower()
    assert "do not name a cause" in joined


# --- the shape every new detector shares ----------------------------
_NEW = [CREATININE_ELEVATION, REDUCED_EGFR, UREA_ELEVATION, ALBUMINURIA,
        ALT_ELEVATION, AST_ELEVATION, LOW_ALBUMIN, TSH_ELEVATION,
        TSH_SUPPRESSION, HYPONATREMIA, HYPERKALEMIA, HYPOCALCEMIA,
        LOW_BICARBONATE, RDW_ELEVATION]


@pytest.mark.parametrize("detector", _NEW, ids=lambda d: d.contract.code)
def test_a_detector_stays_silent_when_its_analyte_is_absent(detector):
    """Silence and 'I cannot tell' are different answers. A thyroid report
    should not carry a notice about missing sodium."""
    unrelated = _evidence(("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0"))
    assert detector.evaluate(unrelated) is None


@pytest.mark.parametrize("detector", _NEW, ids=lambda d: d.contract.code)
def test_every_new_detector_states_what_it_has_not_had_measured(detector):
    contract = detector.contract
    assert contract.validation_note.strip()
    assert contract.exclusion_rules, f"{contract.code} names no failure mode"


def test_the_registry_grew_without_losing_the_rules_it_already_had():
    codes = registry.known_codes()
    assert len(codes) >= 35
    for detector in registry.all_detectors():
        assert KB.get(detector.contract.code) is not None
        assert KB.get(detector.contract.code).must_not_say


# --- what is represented but deliberately has no detector -----------
#: Analytes the pipeline can read and compare, for which no level-2 pattern
#: exists on purpose. Listing them here makes each omission a decision that
#: someone wrote down rather than a gap nobody noticed, and the test below
#: fails if a detector is added for one without removing it from this list.
DELIBERATELY_NO_DETECTOR = {
    # A percentage differential says nothing on its own about whether the
    # absolute count is normal: a raised lymphocyte percentage with a low
    # total white count is a normal lymphocyte count. Neutropenia and
    # lymphopenia matter clinically and both need the absolute count, which
    # the unit rules refuse to derive from a percentage.
    "neutrophils", "lymphocytes", "monocytes", "basophils",
    # Red cell indices that are read as part of a picture, never alone.
    "hematocrit", "rbc", "mch", "mchc",
    # Carried so a higher level can use them; not patterns by themselves. A
    # raised direct bilirubin is read as a fraction of the total, chloride as
    # part of an anion gap, and a free T3 mostly matters when the TSH is
    # already suppressed.
    "bilirubin_direct", "total_protein", "chloride", "free_t3",
}


def test_every_readable_analyte_either_has_a_detector_or_a_stated_reason():
    """A body system with no detector should be a decision, not an oversight."""
    from intelligence.document.normalization.units import CANONICAL_UNIT

    covered = set()
    for detector in registry.all_detectors():
        covered.update(
            requirement.key
            for requirement in detector.contract.required_evidence
            + detector.contract.optional_evidence
            if not requirement.is_finding
        )

    unexplained = set(CANONICAL_UNIT) - covered - DELIBERATELY_NO_DETECTOR
    assert not unexplained, (
        f"{sorted(unexplained)} can be read but nothing reads them. Either "
        f"add a detector or record why there is none."
    )

    stale = DELIBERATELY_NO_DETECTOR & covered
    assert not stale, (
        f"{sorted(stale)} now has a detector; take it off the list."
    )

