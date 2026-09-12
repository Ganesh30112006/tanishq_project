"""Deterministic validation, and which kind of "no" a value gets.

The statuses are different kinds of answer rather than severity levels, and
the distinction that earns its keep is AMBIGUOUS against NEEDS_REVIEW: the
first says the parser could not establish what was measured, the second says
it did and a person must confirm what the fact means. Collapsing them would
make a report nobody could read look like one that was read perfectly.

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
    # value is still OBSERVED. Only implausible values are INVALID.
    assert result.status is ValueStatus.OBSERVED


def test_an_implausible_value_is_invalid():
    """A read error, not a sick patient - and a different answer from "we
    could not tell what this was"."""
    # 200 g/dL -> 2000 g/L, far past the CBC schema's plausibility ceiling.
    result = validate_value(_raw("Hemoglobin", 200.0, "g/dL", "13.0 - 17.0"), schema=CBC)
    assert result.status is ValueStatus.INVALID
    assert result.reason == "outside_plausibility_bounds"
    assert any("plausibility bounds" in i for i in result.issues)


def test_a_non_numeric_value_is_ambiguous_not_a_review_item():
    """There is no fact here to review."""
    result = validate_value(_raw("Hemoglobin", None, "g/dL"), schema=CBC)
    assert result.status is ValueStatus.AMBIGUOUS
    assert result.reason == "value_is_not_numeric"
    assert not result.persists_clinical_value


def test_an_unrecognised_analyte_is_ambiguous_with_a_clear_reason():
    result = validate_value(_raw("Rhubarb Level", 5.0, "mg/dL", "1 - 9"), schema=CBC)
    assert result.status is ValueStatus.AMBIGUOUS
    assert result.reason == "unrecognised_analyte"
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
    # No schema means no plausibility ceiling, so it cannot be INVALID here.
    assert result.status is ValueStatus.OBSERVED


# --- the result and its range must be the same quantity -------------
#
# Found on a real report: every row printed its unit in the range column
# ("13.5 - 17.5 g/dL"), the range parser was anchored and could not read it,
# and so not one of nine correctly extracted results could be interpreted.
#
# Making the range's unit readable raises the question it was hiding: what
# happens when the two units differ. Comparing 5.4 mg/dL against < 200 mmol/L
# gives a confident, wrong answer, and the report prints everything needed to
# avoid it - so the relationship is established and named first.

from intelligence.document.contracts import UnitRelation  # noqa: E402


class TestTheUnitRelationIsEstablishedNotAssumed:
    def test_the_same_printed_unit_on_both_sides(self):
        result = validate_value(
            _raw("Hemoglobin", 13.8, "g/dL", "13.5 - 17.5 g/dL"), schema=CBC
        )
        assert result.unit_relation is UnitRelation.SAME_UNIT
        assert result.reference.unit == "g/dL"
        assert result.reference_status is ReferenceStatus.WITHIN
        assert result.status is ValueStatus.OBSERVED

    def test_a_range_printing_no_unit_of_its_own_means_the_result_s_unit(self):
        """The column convention, and how most ranges are printed."""
        result = validate_value(
            _raw("Hemoglobin", 13.8, "g/dL", "13.5 - 17.5"), schema=CBC
        )
        assert result.unit_relation is UnitRelation.SAME_UNIT
        assert result.reference.unit == ""
        assert result.status is ValueStatus.OBSERVED

    def test_different_units_with_a_verified_conversion_are_compared_converted(self):
        """228 mg/dL is 5.9 mmol/L, which is above 5.2 - and 150 mg/dL is
        3.9 mmol/L, which is not. Comparing the printed numbers would call
        both of them high."""
        high = validate_value(_raw("Total Cholesterol", 228, "mg/dL", "< 5.2 mmol/L"))
        assert high.unit_relation is UnitRelation.CONVERTIBLE
        assert high.reference_status is ReferenceStatus.ABOVE

        ok = validate_value(_raw("Total Cholesterol", 150, "mg/dL", "< 5.2 mmol/L"))
        assert ok.unit_relation is UnitRelation.CONVERTIBLE
        assert ok.reference_status is ReferenceStatus.WITHIN
        assert ok.status is ValueStatus.OBSERVED

    def test_the_printed_range_is_never_rewritten_by_the_conversion(self):
        """The comparison happens in the canonical unit; what the laboratory
        printed is kept exactly as printed, because the printed unit is what
        says which quantity was meant."""
        result = validate_value(_raw("Total Cholesterol", 228, "mg/dL", "< 5.2 mmol/L"))
        assert result.reference.text == "< 5.2 mmol/L"
        assert result.reference.high == 5.2
        assert result.reference.unit == "mmol/L"
        assert result.value == 228
        assert result.unit == "mg/dL"

    def test_two_recognised_units_with_no_conversion_are_incompatible(self):
        result = validate_value(
            _raw("Hemoglobin", 13.8, "g/dL", "4.0 - 11.0 10^9/L"), schema=CBC
        )
        assert result.unit_relation is UnitRelation.INCOMPATIBLE
        assert result.reference_status is ReferenceStatus.UNKNOWN
        assert result.status is ValueStatus.NEEDS_REVIEW
        assert result.reason == "reference_unit_not_comparable"

    def test_a_unit_this_system_does_not_model_is_unknown_not_incompatible(self):
        """Not knowing a unit is not the same as knowing the two disagree."""
        result = validate_value(
            _raw("Hemoglobin", 13.8, "g/dL", "13.5 - 17.5 furlongs"), schema=CBC
        )
        assert result.unit_relation is UnitRelation.UNKNOWN
        assert result.status is ValueStatus.NEEDS_REVIEW
        assert result.reason == "reference_unit_not_comparable"

    def test_a_value_with_no_unit_cannot_be_related_to_a_range_that_has_one(self):
        result = validate_value(_raw("Hemoglobin", 13.8, "", "13.5 - 17.5 g/dL"))
        assert result.unit_relation is UnitRelation.UNKNOWN
        assert result.status is ValueStatus.AMBIGUOUS
        assert result.reason == "no_unit"

    def test_a_range_whose_two_ends_disagree_is_not_resolved_by_picking_one(self):
        result = validate_value(
            _raw("Hemoglobin", 13.8, "g/dL", "13.5 g/dL - 17.5 g/L"), schema=CBC
        )
        assert result.reference.kind == "unparsed"
        assert result.reference_status is ReferenceStatus.UNKNOWN
        assert result.status is ValueStatus.NEEDS_REVIEW


class TestAPlateletCountIsNotGuessedFromItsAnalyte:
    """A missing unit is not a known conventional unit.

    Platelets are printed as /uL, as 10^9/L, and on Indian reports as a count
    in lakh. The parser has the number either way; what it must not do is
    decide which scale was meant because it knows what platelets usually look
    like.
    """

    def test_a_bare_number_says_no_unit(self):
        result = validate_value(_raw("Platelets", 2.3, ""))
        assert result.value == 2.3
        assert result.unit == ""
        assert result.status is ValueStatus.AMBIGUOUS
        assert result.reason == "no_unit"

    def test_a_printed_scale_is_read_and_refused_for_the_honest_reason(self):
        """"lakh/uL" is a unit, and this system does not have a rule for it.
        Saying "no unit" would be untrue and would mislead whoever reviews the
        refusal."""
        result = validate_value(
            _raw("Platelet Count", 2.3, "lakh/\u00b5L", "1.5 - 4.5 lakh/\u00b5L")
        )
        assert result.unit == "lakh/\u00b5L"
        assert result.status is ValueStatus.AMBIGUOUS
        assert result.reason == "unit_not_convertible_for_analyte"
        assert not result.persists_clinical_value

    def test_neither_scale_is_silently_converted_into_the_other(self):
        lakh = validate_value(_raw("Platelet Count", 2.3, "lakh/\u00b5L"))
        assert lakh.normalized is None or not lakh.normalized.convertible

    def test_the_conventional_units_are_read_normally(self):
        for unit, value in (("/\u00b5L", 230000), ("10^9/L", 240)):
            result = validate_value(_raw("Platelet Count", value, unit))
            assert result.status is ValueStatus.OBSERVED, unit
            assert result.analyte == "platelets"
