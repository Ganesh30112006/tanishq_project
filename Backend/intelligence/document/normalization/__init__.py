"""Stage 7: canonical analyte names and canonical units.

``canonical_analyte`` maps a printed label to a known analyte or ``None``.
``normalize_value`` converts a value to the analyte's canonical unit using a
versioned rule table copied from ``apps.common.units`` so the two agree. A
label or unit pair that is not covered is carried through unchanged and
flagged, never guessed.
"""
from __future__ import annotations

from intelligence.document.normalization.analytes import (
    CANONICAL_ANALYTES,
    canonical_analyte,
)
from intelligence.document.normalization.units import (
    CANONICAL_UNIT,
    RULESET_VERSION,
    NormalizedValue,
    normalize_unit_token,
    normalize_value,
)

__all__ = [
    "canonical_analyte",
    "CANONICAL_ANALYTES",
    "normalize_value",
    "normalize_unit_token",
    "NormalizedValue",
    "CANONICAL_UNIT",
    "RULESET_VERSION",
]
