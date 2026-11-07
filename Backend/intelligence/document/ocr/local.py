"""A local OCR provider backed by Tesseract via ``pytesseract``.

Neither ``pytesseract`` nor the Tesseract binary is a hard dependency of this
repository. When either is missing, :meth:`is_available` returns ``False`` and
:meth:`run` returns ``ENGINE_UNAVAILABLE`` with no tokens - which is exactly
the safe path: a photographed report then goes to human review instead of
producing a fabricated read.

To enable it in a deployment: install ``pytesseract`` and the Tesseract engine,
and (optionally) ``Pillow`` for image decoding, then set
``DOCUMENT_OCR_PROVIDER=tesseract-local`` or rely on it being the default.

A scanned PDF is a container of page images, which the engine cannot open
directly. Its pages are rendered with ``pypdfium2`` first, one at a time. Until
2026-11 they were not, so every scanned PDF failed with "cannot identify image
file" - safe, but no scanned report was ever read.
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from intelligence.document.contracts import (
    BoundingBox,
    DocumentMediaType,
    OcrOutcome,
    OcrResult,
    OcrToken,
)
from intelligence.document.ocr.provider import OcrRequest

_NAME = "tesseract-local"

#: Pages are rendered at this resolution, Tesseract's recommended minimum for
#: body text; a lower one costs accuracy on the small print of a results table.
PDF_RENDER_DPI = 300
#: A scanned report longer than this is not rendered: the cost grows with every
#: page, and no laboratory report is this long.
MAX_PDF_PAGES = 30
#: Tesseract's "uniform block" page mode, which treats each row as one line. On
#: rendered reports it kept more single-digit results than sparse mode (--psm 11,
#: 58.8% of values against 54.1%), and the engine's default mode has misread a
#: value (an AST of 27.5 as 215). Lines are still rebuilt by position in ``_layout``.
TESSERACT_CONFIG = "--psm 6"
#: A second, different reading of each page. The two modes make different mistakes,
#: so a number both agree on can be trusted more than either confidence says.
SECOND_READING_CONFIG = "--psm 11"
SECOND_READING = True
#: Clean each page before reading it. See ``preprocess``.
PREPROCESS = True
#: Words nearly every laboratory page prints. Upside-down print can still come out
#: as confident nonsense, but it does not come out as these.
_REPORT_WORDS = frozenset({
    "test", "tests", "result", "results", "range", "reference", "unit", "units", "report",
    "patient", "name", "age", "sex", "gender", "sample", "collected", "received", "reported",
    "page", "lab", "laboratory", "doctor", "serum", "blood", "count", "total", "method",
    "haemoglobin", "hemoglobin", "cholesterol", "glucose", "creatinine", "mg/dl", "g/dl", "u/l",
})
#: A page showing this many of them is the right way up, and is not read again.
UPRIGHT_WORDS = 3


#: Tesseract's English model fine-tuned on laboratory-report lines (see
#: tools/ocr/train_tesseract.py). Not in git, like the other trained models: copied
#: to the server. Without it the engine's own model is used, which reads fewer values.
TRAINED_MODEL_DIR = Path(__file__).resolve().parents[2] / "_artifacts" / "ocr"


def use_trained_model() -> bool:
    """Point the engine at the fine-tuned model when it is installed, and say so."""
    if "TESSDATA_PREFIX" in os.environ:  # chosen explicitly by whoever runs this
        return Path(os.environ["TESSDATA_PREFIX"], "eng.traineddata") == TRAINED_MODEL_DIR / "eng.traineddata"
    if (TRAINED_MODEL_DIR / "eng.traineddata").exists():
        os.environ["TESSDATA_PREFIX"] = str(TRAINED_MODEL_DIR)
        return True
    return False


class LocalTesseractProvider:
    name = _NAME

    def is_available(self) -> bool:
        try:
            import pytesseract
        except ImportError:
            return False
        try:
            pytesseract.get_tesseract_version()
        except Exception:  # noqa: BLE001 - binary missing or broken
            return False
        return True

    def run(self, request: OcrRequest) -> OcrResult:
        if not self.is_available():
            return OcrResult(
                outcome=OcrOutcome.ENGINE_UNAVAILABLE, provider=_NAME,
                detail=(
                    "pytesseract or the Tesseract engine is not installed; "
                    "install both to enable local OCR"
                ),
            )

        if request.media_type is DocumentMediaType.PDF:
            try:
                import pypdfium2  # noqa: F401 - availability probe
            except ImportError:
                return OcrResult(
                    outcome=OcrOutcome.ENGINE_UNAVAILABLE, provider=_NAME,
                    detail=(
                        "pypdfium2 is not installed, so a scanned PDF's pages "
                        "cannot be rendered for OCR"
                    ),
                )

        use_trained_model()
        tokens: list[OcrToken] = []
        second_tokens: list[OcrToken] = []
        stamp_free_tokens: list[OcrToken] = []
        try:
            lang = "+".join(request.languages)
            for page, image in enumerate(_page_images(request), start=1):
                original = image
                image, data, quarter_turns = _read_page(original, lang)
                width, height = image.size
                tokens.extend(self._tokens(data, width, height, page=page))
                if SECOND_READING:
                    other = _read(image, lang, SECOND_READING_CONFIG)
                    second_tokens.extend(self._tokens(other, width, height, page=page))
                    stamp_free_page = _stamp_free_page(original, quarter_turns)
                    if stamp_free_page is not None:
                        other = _read(stamp_free_page, lang)
                        stamp_free_tokens.extend(self._tokens(
                            other, stamp_free_page.width, stamp_free_page.height, page=page,
                        ))
        except Exception as error:  # noqa: BLE001 - a bad image is a result, not a crash
            return OcrResult(
                outcome=OcrOutcome.FAILED, provider=_NAME,
                detail=f"{type(error).__name__}: {error}",
            )

        if not tokens:
            return OcrResult(
                outcome=OcrOutcome.NO_TEXT_FOUND, provider=_NAME,
                detail="the engine ran but recognised no text",
            )

        mean_conf = sum(t.confidence for t in tokens) / len(tokens)
        text, page_starts, word_spans = _layout(tokens)
        outcome = (
            OcrOutcome.OK
            if mean_conf >= request.confidence_floor
            else OcrOutcome.LOW_CONFIDENCE
        )
        return OcrResult(
            outcome=outcome, provider=_NAME, tokens=tokens, text=text,
            mean_confidence=round(mean_conf, 4), page_starts=page_starts,
            word_spans=word_spans, second=_second_result(second_tokens),
            stamp_free=_second_result(stamp_free_tokens),
            detail="" if outcome is OcrOutcome.OK else (
                f"mean confidence {mean_conf:.2f} is below the "
                f"{request.confidence_floor:.2f} floor"
            ),
        )

    @staticmethod
    def _tokens(
        data: dict, width: int, height: int, *, page: int | None = None
    ) -> list[OcrToken]:
        tokens: list[OcrToken] = []
        n = len(data.get("text", []))
        width = width or 1
        height = height or 1
        for i in range(n):
            word = (data["text"][i] or "").strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            token_page = page or int(data.get("page_num", [1] * n)[i] or 1)
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            tokens.append(
                OcrToken(
                    text=word,
                    page=token_page,
                    confidence=round(conf / 100.0, 4),
                    bbox=BoundingBox(
                        page=token_page,
                        x0=round(x / width, 5),
                        y0=round(y / height, 5),
                        x1=round((x + w) / width, 5),
                        y1=round((y + h) / height, 5),
                    ),
                )
            )
        return tokens


def _read(image, lang: str, config: str | None = None) -> dict:
    import pytesseract

    return pytesseract.image_to_data(
        image, lang=lang, config=config or TESSERACT_CONFIG, output_type=pytesseract.Output.DICT,
    )


def _second_result(tokens: list[OcrToken]) -> OcrResult | None:
    if not tokens:
        return None
    text, page_starts, word_spans = _layout(tokens)
    return OcrResult(
        outcome=OcrOutcome.OK, provider=_NAME, text=text, page_starts=page_starts,
        word_spans=word_spans,
        mean_confidence=round(sum(t.confidence for t in tokens) / len(tokens), 4),
    )


def _report_words(data: dict) -> int:
    return sum((word or "").strip(" .,:;()").lower() in _REPORT_WORDS for word in data.get("text", []))


def _read_page(image, lang: str):
    """(the page as read, what the engine found on it, quarter turns applied).

    The way up is found by reading: the engine's own orientation guess needs long
    paragraphs, and a results table has few. Whichever turn shows the most words a
    report would print wins, and most pages settle at the first try.
    """
    if not PREPROCESS:
        return image, _read(image, lang), 0
    from intelligence.document.ocr.preprocess import prepare, straighten, turned

    page = prepare(image)
    data = _read(page, lang)
    best, best_data, best_turns, best_words = page, data, 0, _report_words(data)
    if best_words >= UPRIGHT_WORDS:
        return best, best_data, 0
    for quarter_turns in (1, 2, 3):
        # A page on its side shows no level rows until it is turned, so it is
        # straightened again here.
        other = straighten(turned(page, quarter_turns))
        data = _read(other, lang)
        words = _report_words(data)
        if words > best_words:
            best, best_data, best_turns, best_words = other, data, quarter_turns, words
    return best, best_data, best_turns


def _stamp_free_page(original, quarter_turns: int):
    """The page without its coloured print, or None if it has none or cleaning is off."""
    if not PREPROCESS:
        return None
    from intelligence.document.ocr.preprocess import has_colour, prepare, straighten, turned

    if not has_colour(original):
        return None
    cleaned = prepare(original, drop_colour=True)
    return straighten(turned(cleaned, quarter_turns)) if quarter_turns else cleaned


def _page_images(request: OcrRequest):
    """Each page as an image, one at a time: a photograph is one page, a
    scanned PDF is rendered page by page so only one is held in memory."""
    from PIL import Image

    if request.media_type is not DocumentMediaType.PDF:
        yield Image.open(BytesIO(request.image_bytes))
        return

    import pypdfium2

    pdf = pypdfium2.PdfDocument(request.image_bytes)
    try:
        if len(pdf) > MAX_PDF_PAGES:
            raise ValueError(f"{len(pdf)} pages is more than the {MAX_PDF_PAGES} rendered")
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                yield page.render(scale=PDF_RENDER_DPI / 72).to_pil()
            finally:
                page.close()
    finally:
        pdf.close()


def _lines_by_position(tokens: list[OcrToken]) -> list[tuple[int, list[OcrToken]]]:
    """(page, words left to right) for each printed line, top to bottom.

    A word joins the line above when its centre is within half a word's height
    of that line's centre. Fixed bands of the page height used to do this, and a
    row straddling a band's edge came apart: "Creatinine mg/dl" on one line and
    its result on another, so the result was lost.
    """
    by_page: dict[int, list[OcrToken]] = {}
    for token in tokens:
        by_page.setdefault(token.page, []).append(token)

    def centre(token: OcrToken) -> float:
        return (token.bbox.y0 + token.bbox.y1) / 2 if token.bbox else 0.0

    out: list[tuple[int, list[OcrToken]]] = []
    for page in sorted(by_page):
        words = sorted(by_page[page], key=centre)
        heights = sorted(t.bbox.y1 - t.bbox.y0 for t in words if t.bbox)
        tolerance = heights[len(heights) // 2] / 2 if heights else 0.0
        current: list[OcrToken] = []
        for word in words:
            if current:
                line_centre = sum(centre(t) for t in current) / len(current)
                if abs(centre(word) - line_centre) > tolerance:
                    out.append((page, sorted(current, key=_left)))
                    current = []
            current.append(word)
        if current:
            out.append((page, sorted(current, key=_left)))
    return out


def _left(token: OcrToken) -> float:
    return token.bbox.x0 if token.bbox else 0.0


def _join(tokens: list[OcrToken]) -> tuple[str, tuple[int, ...]]:
    """The text, and the offset at which each page's lines begin."""
    text, starts, _ = _layout(tokens)
    return text, starts


def _layout(
    tokens: list[OcrToken],
) -> tuple[str, tuple[int, ...], tuple[tuple[int, int, float], ...]]:
    """Reassemble lines from tokens using their page and vertical position.

    Returns the text, each page's starting offset, and where each word landed.
    """
    lines = _lines_by_position(tokens)
    out: list[str] = []
    starts: list[int] = []
    spans: list[tuple[int, int, float]] = []
    page, at = None, 0
    for line_page, row in lines:
        line = " ".join(t.text for t in row)
        if line_page != page:
            page = line_page
            starts.append(at)
        word_at = at
        for token in row:
            spans.append((word_at, word_at + len(token.text), token.confidence))
            word_at += len(token.text) + 1
        out.append(line)
        at += len(line) + 1
    return "\n".join(out), tuple(starts), tuple(spans)
