"""File validation and text-layer detection.

The theme across both: what the uploader says the file is carries no weight,
and "there is no readable text here" is a clean result, not a crash.
"""
from __future__ import annotations

from intelligence.document.contracts import DocumentMediaType, TextSource
from intelligence.document.ingestion import extract_text_layer, validate_file

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


# --- validate_file ---------------------------------------------------
def test_type_is_read_from_the_bytes_not_the_declared_content_type():
    result = validate_file(_PNG, declared_type="application/pdf")
    assert result.media_type is DocumentMediaType.PNG
    assert not result.ok
    assert any("declared as application/pdf" in p for p in result.problems)


def test_a_matching_declaration_passes():
    result = validate_file(_PNG, declared_type="image/png")
    assert result.ok and result.media_type is DocumentMediaType.PNG


def test_jpg_alias_declaration_is_accepted():
    result = validate_file(_JPEG, declared_type="image/jpg")
    assert result.ok and result.media_type is DocumentMediaType.JPEG


def test_an_executable_renamed_to_pdf_is_rejected_with_a_specific_reason():
    result = validate_file(b"MZ\x90\x00" + b"\x00" * 64, declared_type="application/pdf")
    assert not result.ok
    assert "Windows executable" in result.problems[0]


def test_an_empty_file_is_rejected():
    result = validate_file(b"", declared_type="application/pdf")
    assert not result.ok and "empty" in result.problems[0]


def test_an_oversize_file_is_flagged():
    result = validate_file(b"%PDF-1.5\n" + b"x" * 200, declared_type="application/pdf",
                           max_bytes=100)
    assert not result.ok
    assert any("over the" in p for p in result.problems)


def test_unrecognised_leading_bytes_are_flagged():
    result = validate_file(b"just some text, no magic", declared_type="")
    assert result.media_type is DocumentMediaType.UNKNOWN
    assert not result.ok


# --- extract_text_layer -------------------------------------------
def test_an_image_never_has_a_text_layer():
    result = extract_text_layer(_PNG, media_type=DocumentMediaType.PNG)
    assert result.source is TextSource.NONE
    assert not result.usable
    assert "OCR is required" in result.detail


def test_a_pdf_with_a_real_text_layer_is_usable(text_pdf):
    pdf = text_pdf([
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 13.4 g/dL",
        "Platelets 240 x10^9/L",
    ])
    result = extract_text_layer(pdf, media_type=DocumentMediaType.PDF)
    assert result.source is TextSource.EMBEDDED_TEXT_LAYER
    assert result.usable
    assert "Hemoglobin" in result.text


def test_a_pdf_with_almost_no_text_is_treated_as_a_scan(text_pdf):
    result = extract_text_layer(text_pdf(["x"]), media_type=DocumentMediaType.PDF)
    assert result.source is TextSource.NONE
    assert not result.usable
    assert "routing to OCR" in result.detail


def test_a_blank_pdf_is_treated_as_a_scan(blank_pdf):
    result = extract_text_layer(blank_pdf, media_type=DocumentMediaType.PDF)
    assert result.source is TextSource.NONE
    assert not result.usable


def test_a_corrupt_pdf_is_a_no_not_an_exception():
    result = extract_text_layer(b"%PDF-1.4 broken", media_type=DocumentMediaType.PDF)
    assert result.source is TextSource.NONE
    assert not result.usable
