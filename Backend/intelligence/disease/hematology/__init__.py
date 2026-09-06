"""Level-3 haematology detectors."""
from __future__ import annotations

from intelligence.disease.hematology.iron_deficiency import (
    IRON_DEFICIENCY,
    IronDeficiencyDetector,
)

DETECTORS = (IRON_DEFICIENCY,)

__all__ = ["IRON_DEFICIENCY", "IronDeficiencyDetector", "DETECTORS"]
