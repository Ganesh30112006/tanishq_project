"""Standard adult resting reference bands for common vital-sign measurements.

These are widely published general-population reference ranges - not a
per-patient clinical judgement and not model output - the same category of
information ``ReportTest.reference_range`` already carries for lab tests
(spec section 11). They exist only to flag a value for follow-up in the UI;
they say nothing about a specific patient's baseline, age group or context,
and must never be read as a diagnosis or a clinical recommendation.

A kind with no entry here has no basis for a status judgement - callers must
return ``None`` rather than guess (spec section 15: "never guess").
"""
from __future__ import annotations

from decimal import Decimal

from apps.health.models import MeasurementKind

# kind -> (low, high) of the normal adult resting range, in the unit
# routinely used for that measurement (mmHg, bpm, %, breaths/min, degC).
REFERENCE_RANGES: dict[str, tuple[float, float]] = {
    MeasurementKind.SYSTOLIC_BP: (90.0, 120.0),
    MeasurementKind.DIASTOLIC_BP: (60.0, 80.0),
    MeasurementKind.HEART_RATE: (60.0, 100.0),
    MeasurementKind.SPO2: (95.0, 100.0),
    MeasurementKind.RESP_RATE: (12.0, 20.0),
    MeasurementKind.TEMPERATURE: (36.1, 37.2),
}

# A value beyond the band edge by more than this fraction of the band's width
# is flagged OUT_OF_RANGE; anything else beyond the edge is ATTENTION.
_OUT_OF_RANGE_FRACTION = 0.5


def measurement_status(kind: str, value: Decimal | float | None) -> str | None:
    """``IN_RANGE`` / ``ATTENTION`` / ``OUT_OF_RANGE``, or ``None`` when there
    is no reference band for this kind or no value to judge against it."""
    if value is None:
        return None
    band = REFERENCE_RANGES.get(kind)
    if band is None:
        return None
    low, high = band
    numeric = float(value)
    if low <= numeric <= high:
        return "IN_RANGE"
    width = high - low
    margin = width * _OUT_OF_RANGE_FRACTION
    if numeric < low - margin or numeric > high + margin:
        return "OUT_OF_RANGE"
    return "ATTENTION"
