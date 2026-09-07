"""Level-3 hepatic detectors."""
from __future__ import annotations

from intelligence.disease.hepatic.injury_pattern import (
    CHOLESTATIC,
    HEPATOCELLULAR,
    LiverShapeDetector,
)

DETECTORS = (HEPATOCELLULAR, CHOLESTATIC)

__all__ = ["HEPATOCELLULAR", "CHOLESTATIC", "LiverShapeDetector", "DETECTORS"]
