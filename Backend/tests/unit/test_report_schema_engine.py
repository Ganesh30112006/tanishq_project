from __future__ import annotations

from decimal import Decimal

from apps.common.enums import CompletenessStatus, ReportClass
from apps.reports.models import ReportSchema
from apps.reports.schema_engine import SchemaEngine

SCHEMA = ReportSchema(
    report_class=ReportClass.LIPID,
    version=3,
    definition={
        "required_fields": ["cholesterol", "hdl", "ldl", "triglycerides"],
        "optional_fields": [],
        "validation_rules": {
            "cholesterol": {"min": 1.0, "max": 20.0},
            "hdl": {"min": 0.1, "max": 5.0},
        },
    },
)
ENGINE = SchemaEngine()


def _v(value, unit="mmol/L"):
    return [{"value": Decimal(str(value)), "unit": unit, "state": "OBSERVED"}]


def test_all_required_present_and_in_range_is_complete():
    result = ENGINE.compare(
        schema=SCHEMA,
        values_by_field={"cholesterol": _v(4.2), "hdl": _v(1.3), "ldl": _v(2.4), "triglycerides": _v(1.1)},
    )
    assert result.status == CompletenessStatus.COMPLETE
    assert result.schema_version == 3


def test_missing_required_field_is_incomplete():
    result = ENGINE.compare(
        schema=SCHEMA,
        values_by_field={"cholesterol": _v(4.2), "hdl": _v(1.3), "ldl": _v(2.4)},
    )
    assert result.status == CompletenessStatus.INCOMPLETE
    assert result.missing_required == ["triglycerides"]


def test_out_of_range_value_is_invalid():
    result = ENGINE.compare(
        schema=SCHEMA,
        values_by_field={
            "cholesterol": _v(99), "hdl": _v(1.3), "ldl": _v(2.4), "triglycerides": _v(1.1)
        },
    )
    assert result.status == CompletenessStatus.INVALID
    assert "cholesterol" in result.invalid


def test_two_distinct_values_for_one_field_is_conflicting():
    result = ENGINE.compare(
        schema=SCHEMA,
        values_by_field={
            "cholesterol": [
                {"value": Decimal("4.2"), "unit": "mmol/L", "state": "OBSERVED"},
                {"value": Decimal("5.9"), "unit": "mmol/L", "state": "OBSERVED"},
            ],
            "hdl": _v(1.3), "ldl": _v(2.4), "triglycerides": _v(1.1),
        },
    )
    assert result.status == CompletenessStatus.CONFLICTING
    assert "cholesterol" in result.conflicting
