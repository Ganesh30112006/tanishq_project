"""OCR / text normalization (spec section 12).

Django owns private file storage and extracts embedded-text-layer PDFs itself
(``apps.reports.ocr``). This endpoint accepts already-extracted text for
normalization (de-hyphenation, whitespace, line joining) and reports a
coarse confidence, or a ``document_reference`` for image OCR. Image OCR
requires a real engine; without one it returns ``UNREADABLE`` so Django opens
a review task rather than proceeding on a bad read.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intelligence.security import verify_service_request

router = APIRouter(tags=["ocr"])


class OcrRequest(BaseModel):
    text: str | None = None
    document_reference: str | None = None
    correlation_id: str


class OcrBlock(BaseModel):
    page: int
    text: str
    ocr_confidence: float


class OcrResponse(BaseModel):
    blocks: list[OcrBlock] = Field(default_factory=list)
    text: str = ""
    status: str = "OK"


def _normalize(text: str) -> str:
    text = re.sub(r"-\n(\w)", r"\1", text)          # join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@router.post("/ocr", response_model=OcrResponse)
async def ocr(
    payload: OcrRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> OcrResponse:
    if payload.text and payload.text.strip():
        clean = _normalize(payload.text)
        # Confidence proxy: fraction of lines that look like structured content.
        lines = [ln for ln in clean.splitlines() if ln.strip()]
        structured = sum(1 for ln in lines if re.search(r"[A-Za-z].*[:\d]", ln))
        conf = round(structured / len(lines), 3) if lines else 0.0
        return OcrResponse(
            blocks=[OcrBlock(page=1, text=clean, ocr_confidence=max(conf, 0.5))],
            text=clean,
            status="OK",
        )
    return OcrResponse(blocks=[], text="", status="UNREADABLE")
