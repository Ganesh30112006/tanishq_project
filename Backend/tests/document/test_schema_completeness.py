"""Comparing an extracted report against its schema.

The five outcomes have a strict precedence - a report that is both missing a
field and has a conflicting one is CONFLICTING, because that is the more
serious problem to put in front of a reviewer. These tests pin that ordering
and the alias / unit / plausibility handling around it.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import CompletenessOutcome, ReportType
from intelligence.document.schemas import (
    ExtractedValue,
    assess_completeness,
    get_schema,
    known_schema_types,
)


@pytest.fixture
def lipid_schema():
    return get_schema(ReportType.LIPID_PROFILE)


def _v(label, value, unit="mmol/L"):
    return ExtractedValue(label=label, value=value, unit=unit)


def test_a_full_in_range_report_is_complete(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("hdl cholesterol", 1.2),
        _v("ldl cholesterol", 3.0), _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.COMPLETE
    assert report.is_complete


def test_a_missing_required_field_is_incomplete(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("hdl cholesterol", 1.2),
        _v("ldl cholesterol", 3.0),
    ])
    assert report.outcome is CompletenessOutcome.INCOMPLETE
    assert report.missing_required == ["triglycerides"]


def test_an_out_of_range_value_is_invalid(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 900.0), _v("hdl cholesterol", 1.2),
        _v("ldl cholesterol", 3.0), _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.INVALID
    assert "cholesterol" in report.invalid


def test_a_missing_unit_is_ambiguous_not_invalid(lipid_schema):
    report = assess_completeness(lipid_schema, [
        ExtractedValue("total cholesterol", 4.9, ""),
        _v("hdl cholesterol", 1.2), _v("ldl cholesterol", 3.0),
        _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.AMBIGUOUS
    assert "cholesterol" in report.ambiguous


def test_an_unrecognised_unit_is_ambiguous(lipid_schema):
    report = assess_completeness(lipid_schema, [
        ExtractedValue("total cholesterol", 4.9, "furlongs"),
        _v("hdl cholesterol", 1.2), _v("ldl cholesterol", 3.0),
        _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.AMBIGUOUS


def test_a_non_numeric_value_is_ambiguous(lipid_schema):
    report = assess_completeness(lipid_schema, [
        ExtractedValue("total cholesterol", None, "mmol/L", raw="see note"),
        _v("hdl cholesterol", 1.2), _v("ldl cholesterol", 3.0),
        _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.AMBIGUOUS


def test_two_different_values_for_one_field_is_conflicting(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("total cholesterol", 5.6),
        _v("hdl cholesterol", 1.2), _v("ldl cholesterol", 3.0),
        _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.CONFLICTING
    assert "cholesterol" in report.conflicting


def test_the_same_value_twice_is_not_a_conflict(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("total cholesterol", 4.9),
        _v("hdl cholesterol", 1.2), _v("ldl cholesterol", 3.0),
        _v("triglycerides", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.COMPLETE


def test_conflict_outranks_a_missing_field(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("total cholesterol", 5.6),
        _v("hdl cholesterol", 1.2),
        # ldl and triglycerides missing
    ])
    assert report.outcome is CompletenessOutcome.CONFLICTING


def test_aliases_resolve_to_canonical_fields(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("Total Cholesterol", 4.9), _v("HDL", 1.2),
        _v("LDL", 3.0), _v("TG", 1.4),
    ])
    assert report.outcome is CompletenessOutcome.COMPLETE


def test_labels_the_schema_does_not_know_are_recorded_not_ignored(lipid_schema):
    report = assess_completeness(lipid_schema, [
        _v("total cholesterol", 4.9), _v("hdl cholesterol", 1.2),
        _v("ldl cholesterol", 3.0), _v("triglycerides", 1.4),
        _v("apolipoprotein b", 0.9),
    ])
    assert report.outcome is CompletenessOutcome.COMPLETE
    assert "apolipoprotein b" in report.unrecognised_labels


def test_narrative_report_types_have_no_schema():
    """A schema that always read COMPLETE would be worse than none."""
    assert get_schema(ReportType.RADIOLOGY) is None
    assert get_schema(ReportType.DISCHARGE_SUMMARY) is None


def test_the_registry_lists_the_panel_types_it_defines():
    types = known_schema_types()
    assert ReportType.CBC in types
    assert ReportType.HBA1C in types
    assert ReportType.RADIOLOGY not in types
