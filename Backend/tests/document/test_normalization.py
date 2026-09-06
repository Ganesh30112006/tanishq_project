"""Canonical analyte names and versioned unit conversion."""
from __future__ import annotations

from intelligence.document.normalization import (
    RULESET_VERSION,
    canonical_analyte,
    normalize_unit_token,
    normalize_value,
)


# --- analyte names -----------------------------------------------
def test_common_spellings_map_to_one_canonical_name():
    for label in ("Haemoglobin", "HB", "Hgb", "hemoglobin"):
        assert canonical_analyte(label) == "hemoglobin"


def test_schema_aliases_are_included():
    assert canonical_analyte("Total Cholesterol") == "cholesterol"
    assert canonical_analyte("HDL Cholesterol") == "hdl"
    assert canonical_analyte("Glycated Haemoglobin") == "hba1c"


def test_punctuation_and_spacing_do_not_matter():
    assert canonical_analyte("  ldl - c ") == "ldl"
    assert canonical_analyte("HbA1c (Glycated Hemoglobin)") == "hba1c"


def test_an_unknown_label_returns_none_rather_than_a_guess():
    assert canonical_analyte("Serum Rhubarb") is None
    assert canonical_analyte("") is None


# --- units -----------------------------------------------------
def test_unit_token_normalisation():
    assert normalize_unit_token("mg/dL") == "mg/dl"
    assert normalize_unit_token("x10^9/L") == "10^9/l"
    assert normalize_unit_token("furlongs") is None


def test_mg_dl_glucose_converts_to_mmol_l():
    result = normalize_value("glucose", 90.0, "mg/dL")
    assert result.convertible
    assert result.unit == "mmol/L"
    assert abs(result.value - 90.0 * 0.0555) < 1e-9
    assert result.rule_version == RULESET_VERSION


def test_hemoglobin_g_dl_to_g_l_is_times_ten():
    assert normalize_value("hemoglobin", 13.4, "g/dL").value == 134.0


def test_a_value_already_in_canonical_units_is_unchanged():
    result = normalize_value("cholesterol", 4.9, "mmol/L")
    assert result.convertible and result.value == 4.9


def test_hba1c_percent_uses_the_ifcc_affine_rule():
    result = normalize_value("hba1c", 6.0, "%")
    assert result.convertible
    assert abs(result.value - (6.0 * 10.929 - 23.49735)) < 1e-6


def test_an_unknown_analyte_is_passed_through_without_an_error_note():
    result = normalize_value("serum rhubarb", 9.2, "%")
    assert not result.convertible
    assert result.detail == ""          # not an error - just nothing to do
    assert result.value == 9.2


def test_an_absolute_eosinophil_count_has_no_conversion_rule_on_purpose():
    """So it can never be compared against a percentage reference range."""
    percentage = normalize_value("eosinophils", 9.2, "%")
    assert percentage.convertible and percentage.unit == "%"

    absolute = normalize_value("eosinophils", 0.4, "10^9/L")
    assert not absolute.convertible
    assert "no conversion rule" in absolute.detail


def test_a_known_analyte_in_a_bad_unit_is_flagged():
    result = normalize_value("hemoglobin", 13.4, "parsecs")
    assert not result.convertible
    assert "not recognised" in result.detail


def test_a_non_numeric_value_is_reported_as_such():
    result = normalize_value("glucose", None, "mg/dL")
    assert not result.convertible and "not numeric" in result.detail


def test_the_factor_table_matches_django_units():
    """The two conversion tables must not drift apart.

    ``apps.common.units`` is Django code and this is not allowed to import it,
    so the check is a value comparison of the overlapping rules.
    """
    from apps.common.units import _LINEAR_RULES  # noqa: PLC2701 - deliberate parity check
    from intelligence.document.normalization import units as doc_units

    overlap = 0
    for (analyte, unit), (factor, offset) in doc_units._RULES.items():
        key = (analyte, unit)
        if key in _LINEAR_RULES:
            d_factor, d_offset = _LINEAR_RULES[key]
            assert abs(float(d_factor) - factor) < 1e-9, key
            assert abs(float(d_offset) - offset) < 1e-6, key
            overlap += 1
    assert overlap >= 8, "expected the core analyte rules to overlap"
