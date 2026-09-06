"""Every value can be traced back to the text it was read from."""
from __future__ import annotations

from intelligence.document.contracts import TextSource
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.provenance import build_provenance


def _raw():
    return RawExtraction(
        label="Hemoglobin", value_text="13.4", value=13.4, unit="g/dL",
        reference_text="13.0 - 17.0", printed_flag="", page=2,
        line="Hemoglobin 13.4 g/dL 13.0 - 17.0", char_span=(415, 447),
        extraction_confidence=0.85,
    )


def test_text_layer_provenance_names_no_ocr_provider():
    prov = build_provenance(
        _raw(), source_sha256="abc123", text_source=TextSource.EMBEDDED_TEXT_LAYER,
        section="COMPLETE BLOOD COUNT", ocr_provider="tesseract-local",
        ocr_confidence=0.9,
    )
    assert prov.text_source is TextSource.EMBEDDED_TEXT_LAYER
    assert prov.ocr_provider == ""          # ignored - the text was not OCR'd
    assert prov.ocr_confidence is None
    assert prov.page == 2
    assert prov.section == "COMPLETE BLOOD COUNT"
    assert prov.char_span == (415, 447)
    assert prov.source_text == "Hemoglobin 13.4 g/dL 13.0 - 17.0"
    assert prov.extractor_version == "1.0"


def test_ocr_provenance_carries_the_provider_and_confidence():
    prov = build_provenance(
        _raw(), source_sha256="abc123", text_source=TextSource.OCR,
        section="", ocr_provider="tesseract-local", ocr_confidence=0.82,
    )
    assert prov.text_source is TextSource.OCR
    assert prov.ocr_provider == "tesseract-local"
    assert prov.ocr_confidence == 0.82


def test_extraction_confidence_is_carried_through():
    prov = build_provenance(
        _raw(), source_sha256="x", text_source=TextSource.EMBEDDED_TEXT_LAYER,
    )
    assert prov.extraction_confidence == 0.85
