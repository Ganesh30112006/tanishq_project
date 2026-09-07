"""Level-3 renal detectors."""
from __future__ import annotations

from intelligence.disease.renal.chronic_kidney_disease import (
    CHRONIC_KIDNEY_DISEASE,
    ChronicKidneyDiseaseDetector,
)

DETECTORS = (CHRONIC_KIDNEY_DISEASE,)

__all__ = ["CHRONIC_KIDNEY_DISEASE", "ChronicKidneyDiseaseDetector", "DETECTORS"]
