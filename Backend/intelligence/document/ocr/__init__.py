"""Stage 3: OCR, behind an adapter so the engine is swappable.

The rest of the application asks for "the default provider" or a provider by
name and calls :meth:`OCRProvider.run`. Which engine answers - a local
Tesseract, a different local engine, a future hosted one - is a deployment
choice made here, not a fact the caller has to know.

The one rule every provider keeps: OCR output is not clinical truth. A result
carries text, per-token page and bounding box, and a confidence, and it
carries an :class:`~intelligence.document.contracts.OcrOutcome` that can say
the engine was unavailable or found nothing. A provider never raises to signal
an ordinary failure and never returns invented text.
"""
from __future__ import annotations

from intelligence.document.ocr.local import LocalTesseractProvider
from intelligence.document.ocr.provider import OCRProvider, OcrRequest
from intelligence.document.ocr.registry import (
    available_providers,
    default_provider,
    get_provider,
    register_provider,
)

__all__ = [
    "OCRProvider",
    "OcrRequest",
    "LocalTesseractProvider",
    "get_provider",
    "default_provider",
    "available_providers",
    "register_provider",
]
