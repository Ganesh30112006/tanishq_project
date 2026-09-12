"""The same invariant, one level up: whole documents rather than single lines.

Three things can only be decided with the whole document in view, and each is
a way a per-line parser that behaved perfectly could still hand a caller a
fact the report does not support:

* the same analyte printed twice with two different numbers;
* a caller asking about an analyte that is simply not on the report, which
  must be distinguishable from one that is there and unreadable;
* text that OCR returned below the confidence floor, where the line may parse
  beautifully and still be characters nobody should trust.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import (
    OcrOutcome,
    OcrResult,
    ValueStatus,
)
from intelligence.document.pipeline import Disposition, process_document
from intelligence.document.validation import OCR_CONFIDENCE_FLOOR, validate_value
from tests.document.adversarial.corpus import NOT_RESULTS


def _run(text_pdf, lines):
    return process_document(text_pdf(lines), declared_type="application/pdf")


CBC = [
    "COMPLETE BLOOD COUNT",
    "Hemoglobin 13.4 g/dL 13.0 - 17.0",
    "WBC 7.2 10^9/L 4.0 - 11.0",
    "Platelet Count 240 10^9/L 150 - 450",
]


# --- the same analyte, twice, disagreeing ---------------------------
def test_one_analyte_reported_twice_with_different_values_conflicts(text_pdf):
    """Picking the first, the last or the worse would each be a
    defensible-sounding rule that discards half of a contradiction the report
    is telling us about itself."""
    result = _run(text_pdf, [
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 13.4 g/dL 13.0 - 17.0",
        "WBC 7.2 10^9/L 4.0 - 11.0",
        "Platelet Count 240 10^9/L 150 - 450",
        "Hemoglobin 9.8 g/dL 13.0 - 17.0",
    ])
    haemoglobins = [r for r in result.values if r.value.analyte == "hemoglobin"]

    assert len(haemoglobins) == 2
    for record in haemoglobins:
        assert record.value.status is ValueStatus.CONFLICTING
        assert not record.value.persists_clinical_value
    assert result.outcome_for("hemoglobin") is ValueStatus.CONFLICTING
    assert any(i.code == "VALUES_CONFLICTING" and i.severity == "HIGH"
               for i in result.issues)
    assert result.disposition is Disposition.NEEDS_REVIEW


def test_the_same_value_printed_twice_is_not_a_conflict(text_pdf):
    result = _run(text_pdf, [*CBC, "Hemoglobin 13.4 g/dL 13.0 - 17.0"])
    assert result.outcome_for("hemoglobin") is ValueStatus.OBSERVED


def test_the_same_value_in_two_units_is_not_a_conflict(text_pdf):
    """13.4 g/dL and 134 g/L are the same measurement. Comparing before
    normalisation would report a contradiction that is not there."""
    result = _run(text_pdf, [*CBC, "Haemoglobin 134 g/L 130 - 175"])
    assert result.outcome_for("hemoglobin") is ValueStatus.OBSERVED


def test_a_conflict_does_not_spread_to_the_other_analytes(text_pdf):
    result = _run(text_pdf, [*CBC, "Hemoglobin 9.8 g/dL 13.0 - 17.0"])
    assert result.outcome_for("wbc") is ValueStatus.OBSERVED
    assert result.outcome_for("platelets") is ValueStatus.OBSERVED


# --- absent, versus present and unreadable --------------------------
def test_an_analyte_that_is_not_on_the_report_is_not_found(text_pdf):
    result = _run(text_pdf, CBC)
    assert result.outcome_for("tsh") is ValueStatus.NOT_FOUND
    assert result.outcome_for("hemoglobin") is ValueStatus.OBSERVED


def test_an_analyte_that_is_present_but_unparseable_is_not_not_found(text_pdf):
    """The distinction the whole status ladder exists for: 'the report does
    not mention it' and 'the report mentions it and we could not read it'
    need different things from a person."""
    result = _run(text_pdf, [
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 1 3.4 g/dL 13.0 - 17.0",
        "WBC 7.2 10^9/L 4.0 - 11.0",
        "Platelet Count 240 10^9/L 150 - 450",
    ])
    assert result.outcome_for("hemoglobin") is ValueStatus.AMBIGUOUS
    assert result.outcome_for("tsh") is ValueStatus.NOT_FOUND


def test_an_unreadable_document_answers_unreadable_for_everything():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    result = process_document(png, declared_type="image/png")
    if result.disposition is not Disposition.UNREADABLE:
        pytest.skip("an OCR engine is installed; this path needs none")
    assert result.outcome_for("hemoglobin") is ValueStatus.UNREADABLE
    assert result.outcome_for("tsh") is ValueStatus.UNREADABLE


def test_the_worst_answer_wins_when_one_analyte_has_several(text_pdf):
    result = _run(text_pdf, [
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 13.4 g/dL 13.0 - 17.0",
        "Hemoglobin 9.8 g/dL 13.0 - 17.0",
        "WBC 7.2 10^9/L 4.0 - 11.0",
        "Platelet Count 240 10^9/L 150 - 450",
    ])
    assert result.outcome_for("hemoglobin") is ValueStatus.CONFLICTING


# --- characters nobody should trust ---------------------------------
def _raw(line):
    from intelligence.document.extraction import extract_raw_values

    return extract_raw_values(line + "\n")[0]


def test_a_perfectly_formed_line_from_bad_ocr_is_unreadable():
    """A confident parse of badly-read text is the most dangerous output this
    module can produce: nothing downstream can tell it from a good one."""
    clean = _raw("Hemoglobin 13.4 g/dL 13.0 - 17.0")

    trusted = validate_value(clean, ocr_confidence=0.95)
    assert trusted.status is ValueStatus.OBSERVED

    doubted = validate_value(clean, ocr_confidence=OCR_CONFIDENCE_FLOOR - 0.01)
    assert doubted.status is ValueStatus.UNREADABLE
    assert doubted.reason == "ocr_below_confidence_floor"
    assert not doubted.persists_clinical_value


def test_text_that_was_never_ocred_is_not_penalised():
    clean = _raw("Hemoglobin 13.4 g/dL 13.0 - 17.0")
    assert validate_value(clean, ocr_confidence=None).status is ValueStatus.OBSERVED


def test_low_confidence_ocr_reaches_validation_through_the_pipeline():
    """The floor is only worth having if the confidence actually arrives."""

    class _Doubtful:
        name = "fake-low-confidence"

        def run(self, request):
            return OcrResult(
                outcome=OcrOutcome.LOW_CONFIDENCE,
                provider=self.name,
                text="COMPLETE BLOOD COUNT\nHemoglobin 13.4 g/dL 13.0 - 17.0\n"
                     "WBC 7.2 10^9/L 4.0 - 11.0\n"
                     "Platelet Count 240 10^9/L 150 - 450\n",
                mean_confidence=0.31,
                detail="deliberately low",
            )

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    result = process_document(
        png, declared_type="image/png", ocr_provider=_Doubtful()
    )
    assert result.values
    assert all(r.value.status is ValueStatus.UNREADABLE for r in result.values)
    assert result.observed_values == []
    assert result.disposition is Disposition.NEEDS_REVIEW


# --- report furniture, through the whole pipeline --------------------
def test_a_page_of_report_furniture_yields_no_clinical_values(text_pdf):
    result = _run(text_pdf, ["LABORATORY REPORT", *NOT_RESULTS])
    assert result.observed_values == []


def test_a_real_report_is_still_read_normally(text_pdf):
    """The guard rails must not have cost us the ordinary case."""
    result = _run(text_pdf, CBC)
    assert result.disposition is Disposition.EXTRACTED
    assert {r.value.analyte for r in result.observed_values} == {
        "hemoglobin", "wbc", "platelets"
    }
