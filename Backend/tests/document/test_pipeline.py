"""The wired pipeline: bytes -> validate -> text/OCR -> classify -> extract.

Each path ends in a named ``Disposition``. UNREADABLE still matters most: an
image with no OCR engine lands there carrying zero extracted content.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import TextSource, ValueStatus
from intelligence.document.ocr import LocalTesseractProvider
from intelligence.document.pipeline import Disposition, process_document

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CBC_LINES = [
    "COMPLETE BLOOD COUNT",
    "Hemoglobin        13.4 g/dL     13.0 - 17.0",
    "WBC               7.2  10^9/L   4.0 - 11.0",
    "Platelet Count    240  10^9/L   150 - 450",
]


def test_a_bad_file_is_rejected_before_any_processing():
    result = process_document(b"MZ\x00\x00", declared_type="application/pdf")
    assert result.disposition is Disposition.REJECTED_FILE
    assert result.text == ""
    assert result.classification is None
    assert result.source_sha256  # still hashed


def test_a_clean_cbc_pdf_is_extracted(text_pdf):
    result = process_document(text_pdf(CBC_LINES), declared_type="application/pdf")

    assert result.disposition is Disposition.EXTRACTED
    assert result.text_source is TextSource.EMBEDDED_TEXT_LAYER
    assert result.ocr is None
    assert result.report_type.value == "CBC"
    observed = {r.value.analyte for r in result.observed_values}
    assert observed == {"hemoglobin", "wbc", "platelets"}
    assert result.completeness.outcome.value == "COMPLETE"


def test_every_extracted_value_carries_provenance(text_pdf):
    result = process_document(text_pdf(CBC_LINES), declared_type="application/pdf")
    for record in result.values:
        prov = record.provenance
        assert prov.source_sha256 == result.source_sha256
        assert prov.page >= 1
        assert prov.section == "COMPLETE BLOOD COUNT"
        assert prov.source_text.strip()
        assert prov.char_span[0] < prov.char_span[1]
        assert prov.text_source is TextSource.EMBEDDED_TEXT_LAYER
        assert prov.extractor == "regex-line"


def test_an_out_of_range_value_is_rejected_not_reported(text_pdf):
    result = process_document(
        text_pdf([
            "COMPLETE BLOOD COUNT",
            "Hemoglobin        1300 g/dL    13.0 - 17.0",  # impossible after x10
            "WBC               7.2  10^9/L   4.0 - 11.0",
            "Platelet Count    240  10^9/L   150 - 450",
        ]),
        declared_type="application/pdf",
    )
    hb = next(r for r in result.values if r.value.analyte == "hemoglobin")
    assert hb.value.status is ValueStatus.INVALID
    assert result.disposition is Disposition.NEEDS_REVIEW
    assert any(i.code == "VALUES_INVALID" and i.severity == "HIGH" for i in result.issues)


def test_a_text_pdf_of_an_unclear_type_needs_review(text_pdf):
    pdf = text_pdf([
        "MISCELLANEOUS NOTE",
        "This page has plenty of words on it but none that identify a report",
        "type to the deterministic classifier, so it should abstain cleanly.",
    ])
    result = process_document(pdf, declared_type="application/pdf")
    assert result.disposition is Disposition.NEEDS_REVIEW
    assert result.report_type is None
    assert any(i.code == "CLASSIFICATION_REVIEW_REQUIRED" for i in result.issues)


def test_an_image_with_no_ocr_engine_is_unreadable_with_nothing_extracted():
    if LocalTesseractProvider().is_available():
        pytest.skip("Tesseract installed; the no-engine path cannot be exercised here")

    result = process_document(_PNG, declared_type="image/png")

    assert result.disposition is Disposition.UNREADABLE
    assert result.text == ""
    assert result.values == []
    assert result.classification is None
    assert any(i.code == "OCR_UNAVAILABLE" and i.severity == "HIGH" for i in result.issues)


def test_a_scanned_pdf_with_no_text_layer_falls_through_to_ocr(blank_pdf):
    if LocalTesseractProvider().is_available():
        pytest.skip("Tesseract installed; would actually OCR the blank page")

    result = process_document(blank_pdf, declared_type="application/pdf")
    assert result.disposition is Disposition.UNREADABLE
    assert result.text_layer is not None
    assert result.text_layer.source is TextSource.NONE
    assert result.ocr is not None  # OCR was attempted


def test_an_injected_ocr_provider_feeds_the_full_pipeline():
    from intelligence.document.contracts import OcrOutcome, OcrResult, OcrToken

    class StubOCR:
        name = "stub"

        def is_available(self) -> bool:
            return True

        def run(self, request):
            text = (
                "LIPID PROFILE\n"
                "Total Cholesterol 4.9 mmol/L 0.0 - 5.2\n"
                "HDL Cholesterol 1.2 mmol/L 1.0 - 2.0\n"
                "LDL Cholesterol 3.0 mmol/L 0.0 - 3.4\n"
                "Triglycerides 1.4 mmol/L 0.0 - 1.7\n"
            )
            return OcrResult(
                outcome=OcrOutcome.OK, provider="stub",
                tokens=[OcrToken(text="LIPID", page=1, confidence=0.97)],
                text=text, mean_confidence=0.97,
            )

    result = process_document(_PNG, declared_type="image/png", ocr_provider=StubOCR())

    assert result.text_source is TextSource.OCR
    assert result.report_type.value == "LIPID"
    assert result.disposition is Disposition.EXTRACTED
    assert {r.value.analyte for r in result.observed_values} == {
        "cholesterol", "hdl", "ldl", "triglycerides"
    }
    # Provenance records the OCR provider and its confidence.
    prov = result.values[0].provenance
    assert prov.text_source is TextSource.OCR
    assert prov.ocr_provider == "stub"
    assert prov.ocr_confidence == 0.97


def test_low_confidence_ocr_is_flagged_but_not_dropped():
    from intelligence.document.contracts import OcrOutcome, OcrResult, OcrToken

    class ShakyOCR:
        name = "shaky"

        def is_available(self) -> bool:
            return True

        def run(self, request):
            text = (
                "GLYCATED HEMOGLOBIN\nHbA1c 6.1 % 4.0 - 5.6\n"
            )
            return OcrResult(
                outcome=OcrOutcome.LOW_CONFIDENCE, provider="shaky",
                tokens=[OcrToken(text="HbA1c", page=1, confidence=0.4)],
                text=text, mean_confidence=0.4, detail="mean confidence 0.40",
            )

    result = process_document(_PNG, declared_type="image/png", ocr_provider=ShakyOCR())
    assert result.text_source is TextSource.OCR
    assert any(i.code == "OCR_LOW_CONFIDENCE" for i in result.issues)
