"""Deterministic validation of one extracted, normalised value.

Turns a raw line plus its normalisation into a :class:`ValidatedValue` with a
:class:`~intelligence.document.contracts.ValueStatus`. The statuses are not
severity levels; they are different *kinds* of answer, and keeping them apart
is what makes the no-fabrication guarantee observable:

``AMBIGUOUS``     the parser could not establish what was measured. There is no
                  value here to be right or wrong about - an unrecognised test
                  name, no unit, a result given as "< 0.01", two numbers where
                  one was expected.
``INVALID``       analyte, value and unit were established, and the number is
                  outside what the assay can produce. A read error, not a sick
                  patient.
``UNREADABLE``    the characters themselves are not trustworthy: OCR returned
                  this text below the confidence floor.
``NEEDS_REVIEW``  there *is* a fact, and it is plausible, but its
                  interpretation is unresolved - a printed H/L flag that
                  disagrees with the computed reference status, an unparseable
                  reference range.
``OBSERVED``      passed every check.

Precedence, worst first, mirrors ``apps.reports.schema_engine`` so the two
engines never disagree about which problem dominates:

    UNREADABLE > INVALID > AMBIGUOUS > NEEDS_REVIEW > OBSERVED

(``CONFLICTING`` is a relationship between two extractions rather than a
property of one, so it is assigned by the pipeline, not here.)

The reference-range *status* is computed here from value vs range. The clinical
*meaning* of an out-of-range value is not - that is the knowledge layer.
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

#: Below this mean OCR confidence the characters are not trustworthy enough to
#: read a clinical number out of, however well-formed the line looks. A
#: confident parse of badly-read text is the most dangerous output this module
#: can produce, because nothing downstream can tell it from a good one.
OCR_CONFIDENCE_FLOOR = 0.55


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
    #: Why the status is what it is, in one short machine-readable token, so a
    #: caller can route without parsing prose.
    reason: str = ""

    @property
    def persists_clinical_value(self) -> bool:
        return self.status.persists_clinical_value


def _reference_status(value: float | None, ref: ReferenceRange) -> ReferenceStatus:
    if value is None or not ref.is_numeric:
        return ReferenceStatus.UNKNOWN
    if ref.low is not None and value < ref.low:
        return ReferenceStatus.BELOW
    if ref.high is not None and value > ref.high:
        return ReferenceStatus.ABOVE
    return ReferenceStatus.WITHIN


def validate_value(
    raw: RawExtraction,
    *,
    schema: ReportSchema | None = None,
    ocr_confidence: float | None = None,
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
    flag_disagrees = (
        printed_status is not None
        and ref_status is not ReferenceStatus.UNKNOWN
        and printed_status is not ref_status
    )
    if flag_disagrees:
        issues.append(
            f"printed flag {raw.printed_flag!r} disagrees with the range "
            f"({ref_status.value})"
        )

    status, reason = _classify(
        raw, analyte, schema, normalized, reference, flag_disagrees, ocr_confidence,
        issues,
    )
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
        reason=reason,
    )


def _classify(
    raw: RawExtraction,
    analyte: str | None,
    schema: ReportSchema | None,
    normalized: NormalizedValue,
    reference: ReferenceRange,
    flag_disagrees: bool,
    ocr_confidence: float | None,
    issues: list[str],
) -> tuple[ValueStatus, str]:
    # 1. The characters themselves are not trustworthy. Nothing parsed out of
    #    them can be, however well-formed the line looks.
    if ocr_confidence is not None and ocr_confidence < OCR_CONFIDENCE_FLOOR:
        issues.append(
            f"OCR mean confidence {ocr_confidence:.2f} is below the floor of "
            f"{OCR_CONFIDENCE_FLOOR}, so the characters cannot be vouched for"
        )
        return ValueStatus.UNREADABLE, "ocr_below_confidence_floor"

    # 2. Could we establish what was measured at all? Each of these means there
    #    is no fact here, as opposed to a fact that looks wrong.
    if raw.value is None:
        return ValueStatus.AMBIGUOUS, _no_value_reason(raw)
    if analyte is None:
        return ValueStatus.AMBIGUOUS, "unrecognised_analyte"
    if not raw.unit:
        return ValueStatus.AMBIGUOUS, "no_unit"
    if not normalized.convertible:
        return ValueStatus.AMBIGUOUS, "unit_not_convertible_for_analyte"

    # 3. The fact is established. Is the number one the assay can produce?
    spec = schema.spec(analyte) if schema else None
    if spec is not None:
        lo, hi = spec.min_value, spec.max_value
        value = normalized.value
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            issues.append(
                f"{value} {normalized.unit} is outside the plausibility bounds "
                f"[{lo}, {hi}] for {analyte}"
            )
            return ValueStatus.INVALID, "outside_plausibility_bounds"

    # 4. The fact is established and plausible. Is its interpretation settled?
    if flag_disagrees:
        return ValueStatus.NEEDS_REVIEW, "printed_flag_disagrees_with_range"
    if raw.reference_text and reference.kind == "unparsed":
        return ValueStatus.NEEDS_REVIEW, "reference_range_unparseable"
    if issues:
        return ValueStatus.NEEDS_REVIEW, "unresolved_extraction_issue"
    return ValueStatus.OBSERVED, ""


def _no_value_reason(raw: RawExtraction) -> str:
    joined = " ".join(raw.issues)
    if "bound rather than a measured value" in joined:
        return "result_is_a_bound_not_a_number"
    if "second number" in joined:
        return "more_than_one_number_on_the_line"
    return "value_is_not_numeric"
