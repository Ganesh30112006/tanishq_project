"""A local OCR provider backed by Tesseract via ``pytesseract``.

Neither ``pytesseract`` nor the Tesseract binary is a hard dependency of this
repository. When either is missing, :meth:`is_available` returns ``False`` and
:meth:`run` returns ``ENGINE_UNAVAILABLE`` with no tokens - which is exactly
the safe path: a photographed report then goes to human review instead of
producing a fabricated read.

To enable it in a deployment: install ``pytesseract`` and the Tesseract engine,
and (optionally) ``Pillow`` for image decoding, then set
``DOCUMENT_OCR_PROVIDER=tesseract-local`` or rely on it being the default.
"""
from __future__ import annotations

from io import BytesIO

from intelligence.document.contracts import (
    BoundingBox,
    OcrOutcome,
    OcrResult,
    OcrToken,
)
from intelligence.document.ocr.provider import OcrRequest

_NAME = "tesseract-local"


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

        try:
            import pytesseract
            from PIL import Image

            image = Image.open(BytesIO(request.image_bytes))
            width, height = image.size
            data = pytesseract.image_to_data(
                image,
                lang="+".join(request.languages),
                output_type=pytesseract.Output.DICT,
            )
        except Exception as error:  # noqa: BLE001 - a bad image is a result, not a crash
            return OcrResult(
                outcome=OcrOutcome.FAILED, provider=_NAME,
                detail=f"{type(error).__name__}: {error}",
            )

        tokens = self._tokens(data, width, height)
        if not tokens:
            return OcrResult(
                outcome=OcrOutcome.NO_TEXT_FOUND, provider=_NAME,
                detail="the engine ran but recognised no text",
            )

        mean_conf = sum(t.confidence for t in tokens) / len(tokens)
        text = _join(tokens)
        outcome = (
            OcrOutcome.OK
            if mean_conf >= request.confidence_floor
            else OcrOutcome.LOW_CONFIDENCE
        )
        return OcrResult(
            outcome=outcome, provider=_NAME, tokens=tokens, text=text,
            mean_confidence=round(mean_conf, 4),
            detail="" if outcome is OcrOutcome.OK else (
                f"mean confidence {mean_conf:.2f} is below the "
                f"{request.confidence_floor:.2f} floor"
            ),
        )

    @staticmethod
    def _tokens(data: dict, width: int, height: int) -> list[OcrToken]:
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
            page = int(data.get("page_num", [1] * n)[i] or 1)
            x, y = int(data["left"][i]), int(data["top"][i])
            w, h = int(data["width"][i]), int(data["height"][i])
            tokens.append(
                OcrToken(
                    text=word,
                    page=page,
                    confidence=round(conf / 100.0, 4),
                    bbox=BoundingBox(
                        page=page,
                        x0=round(x / width, 5),
                        y0=round(y / height, 5),
                        x1=round((x + w) / width, 5),
                        y1=round((y + h) / height, 5),
                    ),
                )
            )
        return tokens


def _join(tokens: list[OcrToken]) -> str:
    """Reassemble lines from tokens using their page and vertical position."""
    lines: dict[tuple[int, int], list[OcrToken]] = {}
    for token in tokens:
        band = int((token.bbox.y0 if token.bbox else 0.0) * 200)
        lines.setdefault((token.page, band), []).append(token)
    out: list[str] = []
    for _key in sorted(lines):
        row = sorted(lines[_key], key=lambda t: t.bbox.x0 if t.bbox else 0.0)
        out.append(" ".join(t.text for t in row))
    return "\n".join(out).strip()
