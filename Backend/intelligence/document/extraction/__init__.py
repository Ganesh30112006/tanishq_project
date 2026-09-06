"""Stage 6: pull clinical values out of classified report text.

Deterministic and line-oriented. ``extract_raw_values`` finds candidate result
lines; ``parse_reference_range`` turns a printed range into numbers or admits
it could not. Nothing here converts units, canonicalises names or judges
whether a value is normal - those are :mod:`intelligence.document.normalization`
and :mod:`intelligence.document.validation`. A line that cannot be parsed
cleanly is skipped, never half-guessed.
"""
from __future__ import annotations

from intelligence.document.extraction.analytes import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    RawExtraction,
    extract_raw_values,
)
from intelligence.document.extraction.reference import (
    ReferenceRange,
    parse_reference_range,
)

__all__ = [
    "RawExtraction",
    "extract_raw_values",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "ReferenceRange",
    "parse_reference_range",
]
