"""Stage 9 (Phase 3): record where every value came from.

Not yet implemented. For each extracted value, records the source document
hash, page, section, text span, the extraction method (embedded text or a
named OCR provider) and the confidences at each stage, so a clinician can trace
any number back to the pixels it was read from.
"""
from __future__ import annotations
