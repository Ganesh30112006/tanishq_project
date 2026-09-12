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

from intelligence.document.contracts import (
    ReferenceStatus,
    UnitRelation,
    ValueStatus,
)
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.extraction.reference import (
    ReferenceRange,
    parse_reference_range,
)
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.normalization.units import (
    NormalizedValue,
    normalize_unit_token,
    normalize_value,
)
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
    #: Whether the result and its printed range could be compared at all, and
    #: on what basis. Sent over the wire rather than re-derived, because a
    #: caller that guesses this wrong compares two different quantities.
    unit_relation: UnitRelation
    printed_flag: str
    status: ValueStatus
    issues: list[str] = field(default_factory=list)
    #: Why the status is what it is, in one short machine-readable token, so a
    #: caller can route without parsing prose.
    reason: str = ""

    @property
    def persists_clinical_value(self) -> bool:
        return self.status.persists_clinical_value


def unit_relation(
    analyte: str | None, result_unit: str, ref: ReferenceRange
) -> UnitRelation:
    """Establish whether a result and its printed range may be compared.

    Never assumes. The printed unit is what says which quantity the laboratory
    meant - the same argument that makes BUN and urea two analytes rather than
    one with two names - so a range printed in a different unit is reconciled
    through a verified conversion or not at all.
    """
    printed = (ref.unit or "").strip()
    if not printed:
        # The range column carried no unit of its own. On every layout this
        # system has seen that means "the same unit as the result", and it is
        # how most reference ranges are printed.
        return UnitRelation.SAME_UNIT
    if not result_unit.strip():
        return UnitRelation.UNKNOWN
    if printed.lower() == result_unit.strip().lower():
        return UnitRelation.SAME_UNIT

    left = normalize_unit_token(result_unit)
    right = normalize_unit_token(printed)
    if left is None or right is None:
        # One of them is not a unit this system models. "lakh/uL" is a real
        # unit on a real report and not knowing it is not the same as knowing
        # the two disagree.
        return UnitRelation.UNKNOWN
    if left == right:
        return UnitRelation.SAME_UNIT
    if analyte is None:
        return UnitRelation.UNKNOWN

    # Both recognised and different: only a conversion rule for this analyte
    # can reconcile them, and the rule is chosen by the analyte, never by the
    # number.
    here = normalize_value(analyte, 1.0, result_unit)
    there = normalize_value(analyte, 1.0, printed)
    if here.convertible and there.convertible and here.unit == there.unit:
        return UnitRelation.CONVERTIBLE
    return UnitRelation.INCOMPATIBLE


def _in_canonical(analyte: str | None, value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    if analyte is None:
        return value
    converted = normalize_value(analyte, value, unit)
    return converted.value if converted.convertible else value


def _reference_status(
    value: float | None,
    ref: ReferenceRange,
    *,
    analyte: str | None = None,
    result_unit: str = "",
    relation: UnitRelation = UnitRelation.SAME_UNIT,
) -> ReferenceStatus:
    if value is None or not ref.is_numeric or not relation.comparable:
        return ReferenceStatus.UNKNOWN

    if relation is UnitRelation.CONVERTIBLE:
        # Compare in the canonical unit. Both the printed result and the
        # printed range keep the numbers and units the laboratory wrote; only
        # this comparison happens elsewhere.
        value = _in_canonical(analyte, value, result_unit)
        low = _in_canonical(analyte, ref.low, ref.unit)
        high = _in_canonical(analyte, ref.high, ref.unit)
    else:
        low, high = ref.low, ref.high

    if value is None:
        return ReferenceStatus.UNKNOWN
    if low is not None and value < low:
        return ReferenceStatus.BELOW
    if high is not None and value > high:
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

    # A result and its range may only be compared when their units are the
    # same quantity. Established explicitly, then applied.
    relation = unit_relation(analyte, raw.unit, reference)
    if reference.is_numeric and not relation.comparable:
        issues.append(
            f"the range is printed in {reference.unit!r} and the result in "
            f"{raw.unit!r}, which cannot be reconciled ({relation.value})"
        )
    ref_status = _reference_status(
        raw.value, reference, analyte=analyte, result_unit=raw.unit,
        relation=relation,
    )

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
        issues, relation,
    )
    return ValidatedValue(
        analyte=analyte,
        printed_label=raw.label,
        value=raw.value,
        unit=raw.unit,
        normalized=normalized if raw.value is not None else None,
        reference=reference,
        reference_status=ref_status,
        unit_relation=relation,
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
    relation: UnitRelation,
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
    if reference.is_numeric and not relation.comparable:
        # The value itself is sound; what cannot be established is what the
        # laboratory's range says about it.
        return ValueStatus.NEEDS_REVIEW, "reference_unit_not_comparable"
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
