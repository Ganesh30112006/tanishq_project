"""Can this PDF's text be read without OCR?

A PDF that was produced by a lab information system carries a real text layer
and needs no OCR. A PDF that is a photograph wrapped in a PDF container carries
none. Telling them apart cheaply, and being honest when the answer is "no",
keeps OCR for the cases that actually need it.

An image is never a candidate for this stage - it goes straight to OCR.
"""
from __future__ import annotations

from collections import Counter
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


def _page_text(page) -> str:
    """One page's text with each printed row kept on one line.

    Lab software prints a results table as one text run per cell. pypdf's
    default extraction emits every run on its own line, so "Haemoglobin",
    "13.2" and "g/dL" arrive three lines apart and the line-based extractor -
    correctly - pairs none of them: a table-laid-out report yielded no values
    at all. Layout mode places runs by position, so a row reads as a row.

    Layout mode is used only when it is a re-spacing of the same text. It
    silently ignores text inside a form XObject - which is where HTML-to-PDF
    generators put the whole page - and returned nothing at all for real lab
    reports whose plain extraction was complete. So the layout text must carry
    every printable character the plain text does; otherwise, or if layout mode
    fails, the plain extraction is used, which is what every page got before.
    """
    plain = page.extract_text() or ""
    try:
        layout = page.extract_text(
            extraction_mode="layout", layout_mode_space_vertically=False
        ) or ""
    except Exception:  # noqa: BLE001 - fall back to the previous behaviour
        return plain
    if _printable(plain) - _printable(layout):
        return plain
    return layout


def _printable(text: str) -> Counter[str]:
    # Control characters are left out: a font with no Unicode map yields them,
    # and layout mode drops them without losing anything readable.
    return Counter(ch for ch in text if ch.isprintable() and not ch.isspace())


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
        pages = [_page_text(page) for page in reader.pages]
    except Exception as error:  # noqa: BLE001 - a malformed PDF is a "no", not a crash
        return TextLayerResult(
            source=TextSource.NONE, text="", pages=0, chars=0,
            detail=f"PDF could not be parsed: {type(error).__name__}",
        )

    joined = "\n".join(pages)
    lead = len(joined) - len(joined.lstrip())
    text = joined.strip()
    usable = sum(1 for ch in text if not ch.isspace())

    # Where each page begins in ``text``, so a value can say which page it is on.
    starts, at = [], 0
    for page in pages:
        starts.append(max(at - lead, 0))
        at += len(page) + 1

    if usable >= MIN_USABLE_CHARS:
        return TextLayerResult(
            source=TextSource.EMBEDDED_TEXT_LAYER, text=text,
            pages=len(pages), chars=usable, page_starts=tuple(starts),
        )
    return TextLayerResult(
        source=TextSource.NONE, text="", pages=len(pages), chars=usable,
        detail=(
            f"only {usable} usable characters in {len(pages)} page(s); "
            "treating as a scan and routing to OCR"
        ),
    )
