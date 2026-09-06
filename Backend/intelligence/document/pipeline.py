"""Wire the deterministic stages together, up to where Phase 3 begins.

This is the front half of the pipeline described in the package docstring:

    bytes
      -> validate_file
      -> extract_text_layer        (PDF only)
      -> OCR                        (if there is no usable text layer)
      -> classify

Section detection, extraction, normalisation, validation and provenance are
Phase 3 and are not called here yet. The result object already has slots for
them so that adding those stages does not change this function's shape.

Every early return is a *named* outcome, not an exception. A caller inspects
``result.disposition`` to decide what to do; nothing here decides on its behalf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from intelligence.document.classification import classify
from intelligence.document.contracts import (
    ClassificationResult,
    ClassificationStatus,
    DocumentMediaType,
    FileValidation,
    OcrResult,
    TextLayerResult,
    TextSource,
)
from intelligence.document.ingestion import extract_text_layer, validate_file
from intelligence.document.ocr import default_provider
from intelligence.document.ocr.provider import OcrRequest


class Disposition(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    #: Text was obtained and a report type was identified. Ready for Phase 3.
    READY_FOR_EXTRACTION = "READY_FOR_EXTRACTION"
    #: Text was obtained but the type is unclear - a human should classify it.
    NEEDS_CLASSIFICATION_REVIEW = "NEEDS_CLASSIFICATION_REVIEW"
    #: No text could be obtained by any available means.
    UNREADABLE = "UNREADABLE"
    #: The upload is not a report file we accept.
    REJECTED_FILE = "REJECTED_FILE"


@dataclass(slots=True)
class DocumentResult:
    disposition: Disposition
    file: FileValidation
    text: str = ""
    text_source: TextSource = TextSource.NONE
    text_layer: TextLayerResult | None = None
    ocr: OcrResult | None = None
    classification: ClassificationResult | None = None
    notes: list[str] = field(default_factory=list)


def process_document(
    data: bytes,
    *,
    declared_type: str = "",
    max_bytes: int = 25 * 1024 * 1024,
    ocr_provider=None,
) -> DocumentResult:
    file = validate_file(data, declared_type=declared_type, max_bytes=max_bytes)
    if not file.ok:
        return DocumentResult(
            disposition=Disposition.REJECTED_FILE, file=file,
            notes=list(file.problems),
        )

    text = ""
    source = TextSource.NONE
    layer: TextLayerResult | None = None
    ocr: OcrResult | None = None

    if file.media_type is DocumentMediaType.PDF:
        layer = extract_text_layer(data, media_type=file.media_type)
        if layer.usable:
            text, source = layer.text, TextSource.EMBEDDED_TEXT_LAYER

    if not text:
        provider = ocr_provider or default_provider()
        ocr = provider.run(OcrRequest(image_bytes=data, media_type=file.media_type))
        if ocr.produced_text:
            text, source = ocr.text, TextSource.OCR

    if not text.strip():
        detail = ocr.detail if ocr else (layer.detail if layer else "no text")
        return DocumentResult(
            disposition=Disposition.UNREADABLE, file=file, text_layer=layer,
            ocr=ocr, notes=[detail or "no text could be obtained"],
        )

    result = classify(text)
    disposition = (
        Disposition.READY_FOR_EXTRACTION
        if result.status is ClassificationStatus.CLASSIFIED
        else Disposition.NEEDS_CLASSIFICATION_REVIEW
    )
    return DocumentResult(
        disposition=disposition, file=file, text=text, text_source=source,
        text_layer=layer, ocr=ocr, classification=result,
        notes=[result.detail] if result.detail else [],
    )
