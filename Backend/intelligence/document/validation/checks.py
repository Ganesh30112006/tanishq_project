"""Deterministic validation of one extracted, normalised value.

Turns a raw line plus its normalisation into a :class:`ValidatedValue` with a
:class:`~intelligence.document.contracts.ValueStatus`:

* ``REJECTED``     - outside the analyte's plausibility bounds. A read error,
                     not a sick patient. Never persisted as a clinical value.
* ``NEEDS_REVIEW`` - extracted but unresolved: unrecognised unit, non-numeric
                     value, an unparseable reference range, or a printed H/L
                     flag that disagrees with the computed reference status.
* ``OBSERVED``     - passed every check.

The reference-range *status* is computed here from value vs range. The clinical
*meaning* of an out-of-range value (naming a finding) is not - that is the
knowledge layer, a later phase.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.document.contracts import ReferenceStatus, ValueStatus
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.extraction.reference import (
    ReferenceRange,
    parse_reference_range,
)
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.normalization.units import NormalizedValue, normalize_value
from intelligence.document.schemas.model import ReportSchema

_FLAG_TO_STATUS = {
    "H": ReferenceStatus.ABOVE, "HH": ReferenceStatus.ABOVE,
    "CRITICAL_HIGH": ReferenceStatus.ABOVE,
    "L": ReferenceStatus.BELOW, "LL": ReferenceStatus.BELOW,
    "CRITICAL_LOW": ReferenceStatus.BELOW,
}


@dataclass(slots=True)
class ValidatedValue:
    analyte: str | None
    printed_label: str
    value: float | None
    unit: str
    normalized: NormalizedValue | None
    reference: ReferenceRange
    reference_status: ReferenceStatus
    printed_flag: str
    status: ValueStatus
    issues: list[str] = field(default_factory=list)


def _reference_status(value: float | None, ref: ReferenceRange) -> ReferenceStatus:
    if value is None or not ref.is_numeric:
        return ReferenceStatus.UNKNOWN
    if ref.low is not None and value < ref.low:
        return ReferenceStatus.BELOW
    if ref.high is not None and value > ref.high:
        return ReferenceStatus.ABOVE
    return ReferenceStatus.WITHIN


def validate_value(
    raw: RawExtraction, *, schema: ReportSchema | None = None
) -> ValidatedValue:
    issues = list(raw.issues)
    analyte = canonical_analyte(raw.label)
    if analyte is None:
        issues.append(f"unrecognised analyte {raw.label!r}")

    reference = parse_reference_range(raw.reference_text)
    if raw.reference_text and reference.kind == "unparsed":
        issues.append(f"reference range {raw.reference_text!r} could not be parsed")

    normalized = normalize_value(analyte or raw.label, raw.value, raw.unit)
    if raw.value is not None and not normalized.convertible and normalized.detail:
        issues.append(normalized.detail)

    # Reference-range comparison is done in the value's own reported unit, so it
    # holds even when the analyte is unknown or not convertible.
    ref_status = _reference_status(raw.value, reference)

    printed_status = _FLAG_TO_STATUS.get(raw.printed_flag)
    if (
        printed_status is not None
        and ref_status is not ReferenceStatus.UNKNOWN
        and printed_status is not ref_status
    ):
        issues.append(
            f"printed flag {raw.printed_flag!r} disagrees with the range "
            f"({ref_status.value})"
        )

    status = _status(raw, analyte, schema, normalized, issues)
    return ValidatedValue(
        analyte=analyte,
        printed_label=raw.label,
        value=raw.value,
        unit=raw.unit,
        normalized=normalized if raw.value is not None else None,
        reference=reference,
        reference_status=ref_status,
        printed_flag=raw.printed_flag,
        status=status,
        issues=issues,
    )


def _status(
    raw: RawExtraction,
    analyte: str | None,
    schema: ReportSchema | None,
    normalized: NormalizedValue,
    issues: list[str],
) -> ValueStatus:
    if raw.value is None:
        return ValueStatus.NEEDS_REVIEW

    spec = schema.spec(analyte) if (schema and analyte) else None
    if spec is not None and normalized.convertible:
        lo, hi = spec.min_value, spec.max_value
        v = normalized.value
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            issues.append(
                f"{v} {normalized.unit} is outside the plausibility bounds "
                f"[{lo}, {hi}] for {analyte}"
            )
            return ValueStatus.REJECTED

    if issues:
        return ValueStatus.NEEDS_REVIEW
    return ValueStatus.OBSERVED
