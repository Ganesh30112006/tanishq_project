"""The wired front half: bytes -> validate -> text/OCR -> classify.

Each path ends in a named ``Disposition``. The one that matters most is
UNREADABLE: an image with no OCR engine available must land there, carrying
zero extracted content, rather than anywhere that looks like progress.
"""
from __future__ import annotations

from intelligence.document.contracts import ClassificationStatus, TextSource
from intelligence.document.ocr import LocalTesseractProvider
from intelligence.document.pipeline import Disposition, process_document

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_a_bad_file_is_rejected_before_any_processing():
    result = process_document(b"MZ\x00\x00", declared_type="application/pdf")
    assert result.disposition is Disposition.REJECTED_FILE
    assert result.text == ""
    assert result.classification is None


def test_a_text_pdf_is_read_without_ocr_and_classified(text_pdf):
    pdf = text_pdf([
        "LIPID PROFILE",
        "Total Cholesterol 4.9 mmol/L",
        "HDL Cholesterol 1.2 mmol/L",
        "LDL Cholesterol 3.0 mmol/L",
        "Triglycerides 1.4 mmol/L",
    ])
    result = process_document(pdf, declared_type="application/pdf")

    assert result.disposition is Disposition.READY_FOR_EXTRACTION
    assert result.text_source is TextSource.EMBEDDED_TEXT_LAYER
    assert result.ocr is None
    assert result.classification.status is ClassificationStatus.CLASSIFIED


def test_a_text_pdf_of_an_unclear_type_needs_classification_review(text_pdf):
    pdf = text_pdf([
        "MISCELLANEOUS NOTE",
        "This page has plenty of words on it but none that identify a report",
        "type to the deterministic classifier, so it should abstain cleanly.",
    ])
    result = process_document(pdf, declared_type="application/pdf")
    assert result.disposition is Disposition.NEEDS_CLASSIFICATION_REVIEW
    assert result.classification.report_type is None


def test_an_image_with_no_ocr_engine_is_unreadable_with_nothing_extracted():
    provider = LocalTesseractProvider()
    if provider.is_available():
        import pytest

        pytest.skip("Tesseract installed; the no-engine path cannot be exercised here")

    result = process_document(_PNG, declared_type="image/png")

    assert result.disposition is Disposition.UNREADABLE
    assert result.text == ""
    assert result.classification is None
    assert result.ocr is not None
    assert result.ocr.outcome.value == "ENGINE_UNAVAILABLE"


def test_a_scanned_pdf_with_no_text_layer_falls_through_to_ocr(blank_pdf):
    provider = LocalTesseractProvider()
    if provider.is_available():
        import pytest

        pytest.skip("Tesseract installed; would actually OCR the blank page")

    result = process_document(blank_pdf, declared_type="application/pdf")
    assert result.disposition is Disposition.UNREADABLE
    assert result.text_layer is not None
    assert result.text_layer.source is TextSource.NONE
    assert result.ocr is not None  # OCR was attempted


def test_an_injected_provider_is_used_instead_of_the_default():
    from intelligence.document.contracts import OcrOutcome, OcrResult, OcrToken

    class StubOCR:
        name = "stub"

        def is_available(self) -> bool:
            return True

        def run(self, request):
            text = "HbA1c 6.1 %\nGlycated Hemoglobin\nEstimated Average Glucose 128 mg/dL"
            return OcrResult(
                outcome=OcrOutcome.OK, provider="stub",
                tokens=[OcrToken(text="HbA1c", page=1, confidence=0.97)],
                text=text, mean_confidence=0.97,
            )

    result = process_document(_PNG, declared_type="image/png", ocr_provider=StubOCR())
    assert result.disposition is Disposition.READY_FOR_EXTRACTION
    assert result.text_source is TextSource.OCR
    assert result.classification.report_type is not None
