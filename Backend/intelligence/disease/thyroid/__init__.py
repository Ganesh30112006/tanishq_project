"""Level-3 thyroid detectors."""
from __future__ import annotations

from intelligence.disease.thyroid.hypothyroidism import (
    PRIMARY_HYPOTHYROIDISM,
    SUBCLINICAL_HYPOTHYROIDISM,
)

DETECTORS = (PRIMARY_HYPOTHYROIDISM, SUBCLINICAL_HYPOTHYROIDISM)

__all__ = ["PRIMARY_HYPOTHYROIDISM", "SUBCLINICAL_HYPOTHYROIDISM", "DETECTORS"]
