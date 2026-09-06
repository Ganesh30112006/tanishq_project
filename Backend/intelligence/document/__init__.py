"""Document intelligence: turn an uploaded report file into structured evidence.

This package is a **deterministic library**. It has no database access, makes
no authorization decisions, and calls no language model. Every stage has an
explicit set of outcomes, and an outcome that means "I could not read this" is
a first-class result rather than an exception or an empty string that looks
like success.

The pipeline, in order::

    FILE
      -> file validation            (is it the document type it claims to be?)
      -> text-layer extraction      (can the text be read without OCR?)
         -> if not: OCR             (an adapter; the engine is swappable)
      -> classification             (what kind of report is this?)
      -> section detection          (Phase 3)
      -> clinical extraction        (Phase 3)
      -> unit / reference-range     (Phase 3)
      -> validation                 (Phase 3)
      -> provenance                 (Phase 3)
      -> structured report

Boundaries this package must keep:

* It must never be imported by the cardiovascular pathway (``apps.risk``,
  ``intelligence.ml_service``). A regression test enforces this so that a
  failure here can never affect a risk assessment.
* OCR output is not clinical truth. It carries text, page, bounding box and a
  confidence, and a downstream stage decides whether to trust it.
* A language model, when one is eventually added, receives *validated
  structured evidence* from this package - never a raw document, and never the
  job of extracting a value that was not validated deterministically first.
"""
from __future__ import annotations

from intelligence.document.contracts import (
    BoundingBox,
    ClassificationResult,
    ClassificationStatus,
    CompletenessOutcome,
    DocumentMediaType,
    FileValidation,
    OcrOutcome,
    OcrResult,
    OcrToken,
    ReportType,
    TextLayerResult,
    TextSource,
)

__all__ = [
    "BoundingBox",
    "ClassificationResult",
    "ClassificationStatus",
    "CompletenessOutcome",
    "DocumentMediaType",
    "FileValidation",
    "OcrOutcome",
    "OcrResult",
    "OcrToken",
    "ReportType",
    "TextLayerResult",
    "TextSource",
]
