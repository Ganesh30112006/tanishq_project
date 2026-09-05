from __future__ import annotations

from decimal import Decimal

import pytest

from apps.common.errors import ValidationFailed
from apps.common.units import CONVERSION_RULESET_VERSION, convert


def test_glucose_mgdl_to_mmol_l():
    result = convert("90", "mg/dL", "glucose")
    assert result.normalized_unit == "mmol/L"
    assert result.normalized_value == Decimal("4.9950")
    assert result.original_value == Decimal("90")
    assert result.rule_version == CONVERSION_RULESET_VERSION


def test_identity_conversion_is_stable():
    result = convert("5.4", "mmol/L", "glucose")
    assert result.normalized_value == Decimal("5.4000")


def test_hba1c_percent_to_ifcc():
    result = convert("7.0", "%", "hba1c")
    # (7.0 - 2.15) * 10.929 = 53.006...
    assert result.normalized_unit == "mmol/mol"
    assert result.normalized_value == Decimal("53.0057")


def test_unknown_unit_is_rejected_not_guessed():
    with pytest.raises(ValidationFailed):
        convert("1", "furlongs", "glucose")


def test_unknown_analyte_is_rejected():
    with pytest.raises(ValidationFailed):
        convert("1", "mg/dL", "unobtanium")
