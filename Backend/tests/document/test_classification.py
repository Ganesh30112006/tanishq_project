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
