"""Stage 9: record where every value came from.

``build_provenance`` attaches, to each extracted value, the source document
hash, page, section, character span, the exact source line, the text source
(embedded layer or a named OCR provider) and the per-stage confidences.
"""
from __future__ import annotations

from intelligence.document.provenance.record import Provenance, build_provenance

__all__ = ["Provenance", "build_provenance"]
