"""Deterministic validation: OBSERVED / NEEDS_REVIEW / REJECTED.

The reference-range *status* is computed here; the clinical meaning of an
out-of-range value is not.
"""
from __future__ import annotations

from intelligence.document.contracts import ReferenceStatus, ReportType, ValueStatus
from intelligence.document.extraction.analytes import RawExtraction
from intelligence.document.schemas import get_schema
from intelligence.document.validation import validate_value

CBC = get_schema(ReportType.CBC)


def _raw(label, value, unit, ref="", flag="", issues=()):
    return RawExtraction(
        label=label, value_text=str(value), value=value, unit=unit,
        reference_text=ref, printed_flag=flag, line=f"{label} {value} {unit} {ref}",
        page=1, char_span=(0, 10), extraction_confidence=0.85, issues=tuple(issues),
    )


def test_a_clean_in_range_value_is_observed():
    result = validate_value(_raw("Hemoglobin", 13.4, "g/dL", "13.0 - 17.0"), schema=CBC)
    assert result.status is ValueStatus.OBSERVED
    assert result.analyte == "hemoglobin"
    assert result.reference_status is ReferenceStatus.WITHIN
    assert result.issues == []


def test_a_value_above_the_reference_interval_is_flagged_above_but_still_observed():
    result = validate_value(_raw("Hemoglobin", 18.0, "g/dL", "13.0 - 17.0"), schema=CBC)
    assert result.reference_status is ReferenceStatus.ABOVE
    # Out of the *reference* range is a clinical fact, not a read error - the
    # value is still OBSERVED. Only implausible values are REJECTED.
    assert result.status is ValueStatus.OBSERVED


def test_an_implausible_value_is_rejected():
    # 200 g/dL -> 2000 g/L, far past the CBC schema's plausibility ceiling.
    result = validate_value(_raw("Hemoglobin", 200.0, "g/dL", "13.0 - 17.0"), schema=CBC)
    assert result.status is ValueStatus.REJECTED
    assert any("plausibility bounds" in i for i in result.issues)


def test_a_non_numeric_value_needs_review():
    result = validate_value(_raw("Hemoglobin", None, "g/dL"), schema=CBC)
    assert result.status is ValueStatus.NEEDS_REVIEW


def test_an_unrecognised_analyte_needs_review_with_a_clear_reason():
    result = validate_value(_raw("Rhubarb Level", 5.0, "mg/dL", "1 - 9"), schema=CBC)
    assert result.status is ValueStatus.NEEDS_REVIEW
    assert any("unrecognised analyte" in i for i in result.issues)
    # The reference comparison still runs, in the value's own units.
    assert result.reference_status is ReferenceStatus.WITHIN


def test_a_printed_flag_that_contradicts_the_range_needs_review():
    # Printed "L" but the value sits inside the interval.
    result = validate_value(
        _raw("Hemoglobin", 15.0, "g/dL", "13.0 - 17.0", flag="L"), schema=CBC
    )
    assert result.status is ValueStatus.NEEDS_REVIEW
    assert any("disagrees with the range" in i for i in result.issues)


def test_a_printed_flag_that_matches_the_range_is_fine():
    result = validate_value(
        _raw("Hemoglobin", 18.0, "g/dL", "13.0 - 17.0", flag="H"), schema=CBC
    )
    assert result.reference_status is ReferenceStatus.ABOVE
    assert not any("disagrees" in i for i in result.issues)


def test_an_unparseable_reference_range_needs_review():
    result = validate_value(
        _raw("Hemoglobin", 14.0, "g/dL", "ask the lab"), schema=CBC
    )
    assert result.status is ValueStatus.NEEDS_REVIEW
    assert any("could not be parsed" in i for i in result.issues)


def test_no_reference_range_is_not_an_error():
    result = validate_value(_raw("Hemoglobin", 14.0, "g/dL", ""), schema=CBC)
    assert result.reference_status is ReferenceStatus.UNKNOWN
    assert result.status is ValueStatus.OBSERVED


def test_validation_without_a_schema_still_computes_status_and_reference():
    result = validate_value(_raw("Hemoglobin", 14.0, "g/dL", "13.0 - 17.0"), schema=None)
    assert result.analyte == "hemoglobin"
    assert result.reference_status is ReferenceStatus.WITHIN
    # No schema means no plausibility ceiling, so it cannot be REJECTED here.
    assert result.status is ValueStatus.OBSERVED
