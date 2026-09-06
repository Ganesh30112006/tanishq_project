"""Where a value came from - enough to trace it back to the pixels.

Every value that leaves the pipeline carries one of these. A clinician (or an
auditor) can take a reported number and find the exact page, the exact line of
text, the character span within the extracted text, whether that text came from
an embedded layer or a named OCR engine, and the confidence at each stage.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.document.contracts import TextSource
from intelligence.document.extraction.analytes import RawExtraction


@dataclass(frozen=True, slots=True)
class Provenance:
    #: SHA-256 of the exact document bytes this was read from.
    source_sha256: str
    page: int
    section: str
    #: [start, end) offsets into the pipeline's extracted-text string.
    char_span: tuple[int, int]
    source_text: str
    text_source: TextSource
    #: Name of the OCR provider, or "" when an embedded text layer was used.
    ocr_provider: str
    extractor: str
    extractor_version: str
    ocr_confidence: float | None
    extraction_confidence: float


def build_provenance(
    raw: RawExtraction,
    *,
    source_sha256: str,
    text_source: TextSource,
    section: str = "",
    ocr_provider: str = "",
    ocr_confidence: float | None = None,
) -> Provenance:
    return Provenance(
        source_sha256=source_sha256,
        page=raw.page,
        section=section,
        char_span=raw.char_span,
        source_text=raw.line,
        text_source=text_source,
        ocr_provider=ocr_provider if text_source is TextSource.OCR else "",
        extractor=raw.extractor,
        extractor_version=raw.extractor_version,
        ocr_confidence=ocr_confidence if text_source is TextSource.OCR else None,
        extraction_confidence=raw.extraction_confidence,
    )
