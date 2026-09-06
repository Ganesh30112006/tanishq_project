"""Can this PDF's text be read without OCR?

A PDF that was produced by a lab information system carries a real text layer
and needs no OCR. A PDF that is a photograph wrapped in a PDF container carries
none. Telling them apart cheaply, and being honest when the answer is "no",
keeps OCR for the cases that actually need it.

An image is never a candidate for this stage - it goes straight to OCR.
"""
from __future__ import annotations

from io import BytesIO

from intelligence.document.contracts import (
    DocumentMediaType,
    TextLayerResult,
    TextSource,
)

#: Fewer usable characters than this across the whole document is treated as
#: "no text layer". A scanned PDF often yields a few stray characters from a
#: watermark or a form field; that is not a readable report.
MIN_USABLE_CHARS = 24


def extract_text_layer(
    data: bytes,
    *,
    media_type: DocumentMediaType = DocumentMediaType.PDF,
) -> TextLayerResult:
    if media_type is not DocumentMediaType.PDF:
        return TextLayerResult(
            source=TextSource.NONE, text="", pages=0, chars=0,
            detail=f"{media_type.value} has no embedded text layer; OCR is required",
        )

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        return TextLayerResult(
            source=TextSource.NONE, text="", pages=0, chars=0,
            detail="pypdf is not installed",
        )

    try:
        reader = PdfReader(BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as error:  # noqa: BLE001 - a malformed PDF is a "no", not a crash
        return TextLayerResult(
            source=TextSource.NONE, text="", pages=0, chars=0,
            detail=f"PDF could not be parsed: {type(error).__name__}",
        )

    text = "\n".join(pages).strip()
    usable = sum(1 for ch in text if not ch.isspace())

    if usable >= MIN_USABLE_CHARS:
        return TextLayerResult(
            source=TextSource.EMBEDDED_TEXT_LAYER, text=text,
            pages=len(pages), chars=usable,
        )
    return TextLayerResult(
        source=TextSource.NONE, text="", pages=len(pages), chars=usable,
        detail=(
            f"only {usable} usable characters in {len(pages)} page(s); "
            "treating as a scan and routing to OCR"
        ),
    )
