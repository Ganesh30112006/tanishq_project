"""Levels at which a result can be dangerous today, whatever the report printed.

The patient-facing "see a doctor today" message used to fire only when the
laboratory printed a critical flag (HH, LL, CRITICAL). Many reports print a
plain H or L, or nothing, beside a potassium of 7.0 - and there is no doctor in
this product to notice. These limits close that gap.

What they are, and are not:

* They only ever *add* urgency. A value inside them changes nothing, and the
  laboratory's own critical flag still counts on its own.
* They are deliberately wide: a value past one is far outside any reference
  interval, so a mildly abnormal result never trips them.
* A value misread by the reader can trip one. That is a false alarm in the safe
  direction, the same trade the printed-flag check already makes.
* A value in a unit with no conversion to the limit's unit is not judged at
  all - comparing different quantities would be a guess.

These are not a diagnosis and not this laboratory's own critical-value policy,
which wins wherever a report prints one.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.knowledge.provenance import (
    Applicability,
    Provenance,
    SourceType,
    ValidationStatus,
)

#: Bump when a limit changes; the patient analysis records the version used.
CRITICAL_LIMITS_VERSION = "adult-critical-1"

PROVENANCE = Provenance(
    source_type=SourceType.LITERATURE,
    source=(
        "the outer bounds of widely published adult laboratory critical-value "
        "(panic value) lists"
    ),
    applicability=Applicability.UNKNOWN,
    validation_status=ValidationStatus.NOT_VALIDATED,
    what_would_validate_it=(
        "Review by a clinical pathologist against the critical-value policies of "
        "the laboratories whose reports this system reads, and against the "
        "population it serves. Until then every limit is set wide, so that it "
        "errs towards telling someone to see a doctor."
    ),
)


@dataclass(frozen=True, slots=True)
class CriticalLimit:
    analyte: str
    #: The canonical unit the reader normalises this analyte to.
    unit: str
    low: float | None
    high: float | None


LIMITS: tuple[CriticalLimit, ...] = (
    CriticalLimit("potassium", "mmol/L", 2.5, 6.5),
    CriticalLimit("sodium", "mmol/L", 120.0, 160.0),
    CriticalLimit("calcium", "mmol/L", 1.65, 3.25),        # 6.6 / 13 mg/dL
    CriticalLimit("glucose", "mmol/L", 2.8, 22.2),         # 50 / 400 mg/dL
    CriticalLimit("fasting_glucose", "mmol/L", 2.8, 22.2),
    CriticalLimit("random_glucose", "mmol/L", 2.8, 22.2),
    CriticalLimit("hemoglobin", "g/L", 70.0, 200.0),       # 7 / 20 g/dL
    CriticalLimit("platelets", "10^9/L", 20.0, 1000.0),    # 20,000 / 10 lakh per uL
    CriticalLimit("wbc", "10^9/L", 2.0, 30.0),
)

_BY_ANALYTE = {limit.analyte: limit for limit in LIMITS}


def beyond_critical_limit(
    analyte: str | None, *, value: float | None, unit: str,
    normalized_value: float | None = None, normalized_unit: str = "",
) -> bool:
    """True when the result is past a danger limit, in a unit it can be compared in."""
    limit = _BY_ANALYTE.get((analyte or "").strip().lower())
    if limit is None:
        return False
    if normalized_value is not None and normalized_unit == limit.unit:
        number = normalized_value
    elif value is not None and unit == limit.unit:
        number = value
    else:
        return False
    if limit.low is not None and number < limit.low:
        return True
    return limit.high is not None and number > limit.high


__all__ = ["CRITICAL_LIMITS_VERSION", "LIMITS", "PROVENANCE", "beyond_critical_limit"]
