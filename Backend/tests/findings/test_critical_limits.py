"""Danger limits: they add urgency the printed flag missed, and judge nothing
they cannot compare."""
from __future__ import annotations

import pytest

from intelligence.knowledge.critical_limits import LIMITS, PROVENANCE, beyond_critical_limit
from intelligence.knowledge.provenance import ValidationStatus


@pytest.mark.parametrize(
    ("analyte", "value", "unit", "expected"),
    [
        ("potassium", 7.0, "mmol/L", True),
        ("potassium", 2.2, "mmol/L", True),
        ("potassium", 5.6, "mmol/L", False),   # abnormal, not dangerous
        ("sodium", 118.0, "mmol/L", True),
        ("hemoglobin", 50.0, "g/L", True),
        ("hemoglobin", 105.0, "g/L", False),
        ("platelets", 15.0, "10^9/L", True),
        ("wbc", 45.0, "10^9/L", True),
        ("hba1c", 99.0, "mmol/mol", False),     # no limit for this analyte
    ],
)
def test_limits(analyte, value, unit, expected):
    assert beyond_critical_limit(analyte, value=value, unit=unit) is expected


def test_the_normalised_value_is_used_when_the_report_printed_another_unit():
    # 450 mg/dL printed; the reader normalised it to 25 mmol/L.
    assert beyond_critical_limit(
        "glucose", value=450.0, unit="mg/dL", normalized_value=25.0, normalized_unit="mmol/L"
    ) is True
    # The same 450 with no conversion is not compared against a mmol/L limit.
    assert beyond_critical_limit("glucose", value=450.0, unit="mg/dL") is False


def test_limits_declare_they_are_not_validated():
    assert PROVENANCE.validation_status is ValidationStatus.NOT_VALIDATED
    assert PROVENANCE.what_would_validate_it
    assert all(limit.low is not None or limit.high is not None for limit in LIMITS)
