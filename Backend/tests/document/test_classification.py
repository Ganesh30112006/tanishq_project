"""The deterministic report classifier - and, above all, when it abstains.

The classifier's job is to route a clean report and to say REVIEW_REQUIRED
about anything it is not sure of. A wrong confident answer sends the wrong
extraction rules at a document; an honest abstention sends it to a person.
"""
from __future__ import annotations

from intelligence.document.classification import classify
from intelligence.document.contracts import ClassificationStatus, ReportType

CBC = """
COMPLETE BLOOD COUNT WITH DIFFERENTIAL
Hemoglobin      13.4 g/dL
Hematocrit      40.1 %
WBC              6.2 x10^9/L
Platelet count   240 x10^9/L
Neutrophils      58 %
Lymphocytes      33 %
"""

LIPID = """
LIPID PROFILE
Total Cholesterol   4.9 mmol/L
HDL Cholesterol     1.2 mmol/L
LDL Cholesterol     3.0 mmol/L
Triglycerides       1.4 mmol/L
"""

HBA1C = """
GLYCATED HEMOGLOBIN (HbA1c)
HbA1c            6.1 %
Estimated Average Glucose  128 mg/dL
"""

DISCHARGE = """
DISCHARGE SUMMARY
Date of Admission: 2024-03-01
Date of Discharge: 2024-03-06
Hospital Course: The patient was admitted with community-acquired pneumonia.
Discharge Medications: amoxicillin-clavulanate 625 mg three times daily.
Condition on Discharge: stable.
"""


def test_a_clear_cbc_is_classified():
    result = classify(CBC)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.report_type is ReportType.CBC
    assert result.confidence > 0.5
    assert result.signals["CBC"] > result.signals.get("LIPID", 0)


def test_a_clear_lipid_profile_is_classified():
    result = classify(LIPID)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.report_type is ReportType.LIPID_PROFILE


def test_hba1c_beats_plain_glucose_on_a_glycated_hemoglobin_report():
    result = classify(HBA1C)
    assert result.report_type is ReportType.HBA1C


def test_a_discharge_summary_is_classified_not_mistaken_for_a_panel():
    result = classify(DISCHARGE)
    assert result.report_type is ReportType.DISCHARGE_SUMMARY


def test_empty_or_tiny_text_is_review_required():
    for text in ("", "   ", "page 1 of 2"):
        result = classify(text)
        assert result.status is ClassificationStatus.REVIEW_REQUIRED
        assert result.report_type is None


def test_text_with_no_known_keywords_is_review_required():
    result = classify("The quick brown fox jumps over the lazy dog, repeatedly.")
    assert result.status is ClassificationStatus.REVIEW_REQUIRED
    assert result.report_type is None
    assert result.signals == {}


def test_a_document_that_looks_like_two_types_at_once_is_review_required():
    mixed = LIPID + "\n" + "COMPLETE BLOOD COUNT\nHemoglobin 13 g/dL\nWBC 6 x10^9/L\nPlatelet 240\n"
    result = classify(mixed)
    assert result.status is ClassificationStatus.REVIEW_REQUIRED
    assert "does not clear the margin" in result.detail


def test_signals_are_returned_for_audit_even_on_an_abstention():
    result = classify("the report briefly mentioned cholesterol somewhere in passing")
    # One weak hit: recorded in the signals, but nowhere near enough to classify.
    assert result.status is ClassificationStatus.REVIEW_REQUIRED
    assert result.signals.get("LIPID", 0) >= 1


def test_classification_is_deterministic():
    assert classify(CBC) == classify(CBC)


# --- the panels added with the expanded evidence surface ------------
THYROID = """
THYROID FUNCTION TEST
TSH              8.4 uIU/mL     0.4 - 4.0
Free T4          0.7 ng/dL      0.8 - 1.8
Free T3          2.4 pg/mL      2.3 - 4.2
"""

ELECTROLYTES = """
SERUM ELECTROLYTES
Serum Sodium     128 mEq/L      136 - 145
Serum Potassium  5.8 mEq/L      3.5 - 5.1
Serum Chloride   96 mEq/L       98 - 107
Bicarbonate      18 mEq/L       22 - 29
"""

RENAL = """
RENAL FUNCTION TEST
S. Creatinine    1.6 mg/dL      0.6 - 1.2
Blood Urea       58 mg/dL       15 - 40
eGFR             46 mL/min/1.73m2
"""


def test_a_thyroid_panel_is_classified():
    result = classify(THYROID)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.report_type is ReportType.THYROID


def test_an_electrolyte_panel_is_classified():
    result = classify(ELECTROLYTES)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.report_type is ReportType.ELECTROLYTES


def test_a_renal_panel_is_classified():
    result = classify(RENAL)
    assert result.status is ClassificationStatus.CLASSIFIED
    assert result.report_type is ReportType.KIDNEY_FUNCTION


def test_a_renal_and_electrolyte_panel_printed_together_still_abstains():
    """Widening the keyword table must not make the classifier bolder. A
    document carrying two panels is exactly the case a person should see."""
    result = classify(RENAL + ELECTROLYTES)
    assert result.status is ClassificationStatus.REVIEW_REQUIRED


# --- whole words, not fragments ------------------------------------
#
# Found on a real document: a cardiology device report scored six points of
# liver evidence and was classified LIVER_FUNCTION, because substring counting
# read "alt" out of *health*, "ast" out of *atorvastatin* and *least*, and
# "bun" out of *bundle*. Nothing was extracted from it - the analyte table
# refused every number - but the document would have been filed under the
# wrong panel, handed the wrong schema, and counted in the wrong stratum of
# the shadow pilot.

import pytest  # noqa: E402 - the fixtures above read better before the imports


@pytest.mark.parametrize(
    ("word", "must_not_score"),
    [
        ("health", "LIVER"),          # alt
        ("healthy", "LIVER"),         # alt
        ("Atorvastatin", "LIVER"),    # ast
        ("least", "LIVER"),           # ast
        ("fasting", "LIVER"),         # ast - and this one is on lab reports
        ("gastric", "LIVER"),         # ast
        ("bundle", "KIDNEY"),         # bun
        ("bunch", "KIDNEY"),          # bun
    ],
)
def test_a_keyword_buried_in_an_ordinary_word_scores_nothing(word, must_not_score):
    text = f"Some page of text that happens to contain {word} among other words"
    assert classify(text).signals.get(must_not_score, 0) == 0


@pytest.mark.parametrize(
    "line",
    [
        "ALT 34 U/L",
        "alt: 34 U/L",
        "ALT: 34",
        "ALT/AST ratio 1.2",
        "AST, 29 U/L",
        "(ALT) 34 U/L",
        "SGPT (ALT) 34 U/L",
        "alt    34",
    ],
)
def test_the_keyword_itself_still_counts_however_it_is_punctuated(line):
    """Whole-token matching must not become no matching. Every one of these
    prints a real liver analyte."""
    assert classify(f"LIVER FUNCTION TEST\n{line}\n").signals.get("LIVER", 0) > 0


def test_a_multi_word_term_split_across_a_column_gap_still_counts():
    assert classify("LIVER    FUNCTION\nBilirubin 0.8\n").signals.get("LIVER", 0) >= 5


def test_a_document_with_no_real_keyword_abstains_rather_than_picking_the_nearest():
    """The HeartTrends failure, reduced to the four words that caused it."""
    text = (
        "Health Factors\n"
        "Atorvastatin; Tritace\n"
        "at least as reliable as exercise testing\n"
        "presence of left bundle branch block\n"
    )
    result = classify(text)
    assert result.signals == {}
    assert result.report_type is None
    assert result.status is ClassificationStatus.REVIEW_REQUIRED
    assert "no recognised report-type keywords" in result.detail


def test_a_term_in_explanatory_prose_weighs_less_than_the_same_term_as_a_label():
    """A sentence mentioning a test is talking about it; a column header is
    naming what the document contains."""
    label = classify("LIPID PROFILE\nTotal Cholesterol 228 mg/dL\n")
    prose = classify(
        "The patient was counselled at length about cholesterol and about how "
        "cholesterol is affected by diet over the following months.\n"
    )
    assert prose.signals.get("LIPID", 0) < label.signals["LIPID"]
    assert prose.report_type is None


def test_a_single_weak_analyte_named_in_a_sentence_does_not_score():
    """Weight-1 terms carry no weight in prose at all. 'Monitor his
    creatinine' is a recommendation, not a renal panel."""
    result = classify(
        "Please monitor his uric acid and repeat the study in six months if "
        "the patient remains symptomatic after starting treatment.\n"
    )
    assert result.signals.get("KIDNEY", 0) == 0


@pytest.mark.parametrize(
    ("line", "report_type"),
    [
        ("Triglycerides 210 mg/dL", "LIPID"),
        ("Platelets 240 x10^9/L", "CBC"),
        ("Neutrophils 58 %", "CBC"),
        ("Lymphocytes 33 %", "CBC"),
        ("Eosinophils 2 %", "CBC"),
    ],
)
def test_the_plural_a_report_actually_prints_still_counts(line, report_type):
    """The signal table is written in the singular and reports print the
    plural. Substring counting covered that by accident; whole-token matching
    has to do it on purpose. Caught by a real report whose lipid panel stopped
    being recognised."""
    # Padded past the "too little text to classify" floor with words that
    # signal nothing.
    padding = "Specimen drawn in the morning at the collection centre"
    assert classify(f"{line}\n{padding}\n").signals.get(report_type, 0) > 0


def test_an_abbreviation_is_not_pluralised_into_a_false_positive():
    """'Avoid buns' is dietary advice, not a renal panel."""
    assert classify("Advice: avoid buns and fried food entirely.").signals == {}


# --- the margin boundary -------------------------------------------
def test_the_margin_boundary_is_exactly_as_the_contract_states():
    """A characterisation test for the exact 2.0 case.

    The rule is "the winner must beat the runner-up by at least _MARGIN", so
    a winner scoring exactly twice the runner-up is classified and one point
    below it abstains. This test exists because that boundary decides real
    documents: a discharge summary carrying a full lipid panel and a partial
    CBC lands on it exactly, and it is the difference between filing that
    document as a lipid report and sending it to a person.

    If the policy changes to "strictly more than", this test is what will
    fail, and it should be edited deliberately rather than discovered.
    """
    from intelligence.document.classification.keyword import _MARGIN, _MIN_SCORE

    def outcome(best: int, runner_up: int) -> bool:
        """True when a document with these scores would be classified."""
        return not (best < _MIN_SCORE or best < _MARGIN * max(runner_up, 1))

    assert outcome(12, 6) is True       # exactly 2.0 - classified today
    assert outcome(13, 6) is True       # clearly ahead
    assert outcome(11, 6) is False      # short of the margin
    assert outcome(3, 0) is False       # below the floor, whatever the margin


def test_a_document_carrying_two_panels_sits_on_that_boundary():
    """The real discharge summary, reduced. Recorded so that whichever way the
    policy goes, the case is visible."""
    text = (
        "5. Laboratory Investigations\n"
        "Hemoglobin 13.8 g/dL 13.5 - 17.5 g/dL\n"
        "WBC Count 8,200 /\u00b5L 4,000 - 11,000 /\u00b5L\n"
        "Platelet Count 2.3 lakh/\u00b5L 1.5 - 4.5 lakh/\u00b5L\n"
        "Total Cholesterol 228 mg/dL < 200 mg/dL\n"
        "LDL Cholesterol 148 mg/dL < 130 mg/dL\n"
        "HDL Cholesterol 38 mg/dL \u2265 40 mg/dL\n"
        "Triglycerides 210 mg/dL < 150 mg/dL\n"
    )
    result = classify(text)
    assert result.signals["LIPID"] == 2 * result.signals["CBC"]
    assert result.report_type is ReportType.LIPID_PROFILE
