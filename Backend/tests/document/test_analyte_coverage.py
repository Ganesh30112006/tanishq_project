"""The evidence surface: which analytes the pipeline can actually represent.

A detector is only as good as the evidence it can be handed, so these tests
guard the three tables that decide what a report can become - the canonical
analyte names, the unit-conversion rules, and the report schemas - and check
that they agree with each other rather than drifting apart.

The clinically interesting assertions are the ones about pairs of quantities
that share a printed name but are not the same measurement: urea and BUN, a
percentage and an absolute count, a total and an ionised calcium, a fasting
and a random glucose. Each of those is a place where a plausible-looking
shortcut produces a wrong number with a real reference range beside it.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import ReportType, ValueStatus
from intelligence.document.extraction import extract_raw_values
from intelligence.document.normalization import canonical_analyte, normalize_value
from intelligence.document.normalization.units import (  # noqa: PLC2701
    _RULES,
    CANONICAL_UNIT,
    normalize_unit_token,
)
from intelligence.document.schemas import assess_completeness, get_schema
from intelligence.document.schemas.completeness import ExtractedValue
from intelligence.document.schemas.registry import known_schema_types
from intelligence.document.validation import validate_value
from intelligence.knowledge import reference_ranges as RR


# --- the three tables agree with one another ------------------------
def test_every_modelled_analyte_can_reach_its_canonical_unit():
    """An analyte with no rule into its own canonical unit is unusable."""
    for analyte, unit in CANONICAL_UNIT.items():
        rules = {u for (a, u) in _RULES if a == analyte}
        assert rules, f"{analyte} has a canonical unit but no conversion rule"
        assert normalize_unit_token(unit) in rules, (
            f"{analyte} cannot be normalised from its own canonical unit {unit}"
        )


def test_every_conversion_rule_belongs_to_a_modelled_analyte():
    for analyte, unit in _RULES:
        assert analyte in CANONICAL_UNIT, f"rule for unmodelled analyte {analyte}"
        assert normalize_unit_token(unit) == unit, f"unit {unit} is not a token"


def test_every_schema_field_is_a_canonical_analyte_name():
    for report_type in known_schema_types():
        schema = get_schema(report_type)
        for spec in schema.fields:
            assert canonical_analyte(spec.name) == spec.name, (
                f"{report_type.value}.{spec.name} does not resolve to itself"
            )


def test_every_schema_field_declares_the_canonical_unit_it_is_bounded_in():
    """Plausibility bounds are checked against the normalised value, so the
    schema's canonical unit must be the one the converter produces."""
    for report_type in known_schema_types():
        schema = get_schema(report_type)
        for spec in schema.fields:
            expected = CANONICAL_UNIT.get(spec.name)
            if expected is None:
                continue
            assert spec.canonical_unit == expected, (
                f"{report_type.value}.{spec.name} is bounded in "
                f"{spec.canonical_unit} but normalises to {expected}"
            )
            assert expected in spec.accepted_units, (
                f"{spec.name} would fail its own unit check after conversion"
            )


def test_every_accepted_unit_is_one_the_converter_recognises():
    for report_type in known_schema_types():
        schema = get_schema(report_type)
        for spec in schema.fields:
            for unit in spec.accepted_units:
                assert normalize_unit_token(unit) is not None, (
                    f"{spec.name} accepts {unit!r}, which no rule can read"
                )


def test_the_fallback_range_table_speaks_canonical_units():
    for analyte in RR.known_analytes():
        interval = RR.lookup(analyte)
        assert analyte in CANONICAL_UNIT, f"{analyte} has a range but no unit"
        assert interval.unit == CANONICAL_UNIT[analyte], (
            f"{analyte} range is in {interval.unit}, values arrive in "
            f"{CANONICAL_UNIT[analyte]}"
        )


# --- quantities that share a name but are not the same --------------
def test_urea_and_bun_are_separate_analytes_with_different_factors():
    """Urea weighs its whole molecule; BUN weighs only the nitrogen in it.

    The same printed number in mg/dL is therefore a different amount of urea
    depending on which the report meant - by a factor of about 2.14. Both
    normalise to mmol/L of urea and share a reference interval once there,
    which is precisely why the label has to decide the factor: reading a BUN
    of 20 mg/dL as urea would report 3.3 mmol/L for a patient whose real
    value is 7.1.
    """
    assert canonical_analyte("Blood Urea") == "urea"
    assert canonical_analyte("Blood Urea Nitrogen") == "bun"

    as_urea = normalize_value("urea", 40.0, "mg/dL").value
    as_bun = normalize_value("bun", 40.0, "mg/dL").value
    assert as_urea != as_bun
    assert 2.0 < as_bun / as_urea < 2.3


def test_meq_per_litre_is_halved_for_calcium_and_not_for_sodium():
    """Calcium is divalent. A global 'mEq/L means mmol/L' alias would double
    every calcium result on a report that uses the older unit."""
    assert normalize_value("sodium", 140.0, "mEq/L").value == 140.0
    assert normalize_value("calcium", 4.8, "mEq/L").value == 2.4


def test_an_ionised_calcium_is_never_read_as_a_total_calcium():
    assert canonical_analyte("Ionised Calcium") is None
    assert canonical_analyte("Total Calcium") == "calcium"


def test_rdw_sd_is_not_read_against_the_rdw_cv_interval():
    assert canonical_analyte("RDW-SD") is None
    assert canonical_analyte("RDW-CV") == "rdw"


def test_a_creatinine_clearance_is_not_an_egfr():
    assert canonical_analyte("Creatinine Clearance") is None
    assert normalize_unit_token("mL/min") is None
    assert normalize_unit_token("mL/min/1.73m2") == "ml/min/1.73m2"


def test_a_derived_liver_value_is_not_treated_as_measured():
    for label in ("Globulin", "A/G Ratio", "Indirect Bilirubin"):
        assert canonical_analyte(label) is None, label


@pytest.mark.parametrize("analyte", ["neutrophils", "lymphocytes",
                                     "monocytes", "eosinophils", "basophils"])
def test_no_differential_count_can_be_read_as_an_absolute_number(analyte):
    """The whole differential follows the eosinophil precedent: a percentage
    interval must never be applied to a count in cells per litre."""
    assert CANONICAL_UNIT[analyte] == "%"
    assert normalize_value(analyte, 4.2, "%").convertible
    absolute = normalize_value(analyte, 4.2, "10^9/L")
    assert not absolute.convertible
    assert "no conversion rule" in absolute.detail


# --- glycaemia: which sample was taken changes the answer -----------
def test_a_fasting_and_a_random_glucose_are_different_analytes():
    assert canonical_analyte("Fasting Blood Sugar") == "fasting_glucose"
    assert canonical_analyte("FBS") == "fasting_glucose"
    assert canonical_analyte("Random Blood Sugar") == "random_glucose"
    assert canonical_analyte("PPBS") == "random_glucose"


def test_an_unqualified_glucose_has_no_fallback_range_on_purpose():
    """It cannot be read against the fasting numbers or the random ones, so
    it is not read against either."""
    assert canonical_analyte("Plasma Glucose") == "glucose"
    assert RR.lookup("glucose") is None
    assert RR.lookup("fasting_glucose") is not None
    assert RR.lookup("random_glucose") is not None


def test_a_glucose_report_needs_at_least_one_of_the_three():
    schema = get_schema(ReportType.GLUCOSE)
    empty = assess_completeness(schema, [])
    assert empty.missing_required == ["fasting_glucose or random_glucose or glucose"]

    fasting = assess_completeness(
        schema, [ExtractedValue(label="fasting_glucose", value=5.1, unit="mmol/L")]
    )
    assert fasting.is_complete


# --- the labels real Indian reports actually print ------------------
@pytest.mark.parametrize("label,expected", [
    ("SGPT", "alt"), ("SGPT (ALT)", "alt"), ("SGOT", "ast"),
    ("Alkaline Phosphatase", "alp"), ("GGTP", "ggt"),
    ("S. Creatinine", "creatinine"), ("eGFR", "egfr"),
    ("Total Bilirubin", "bilirubin_total"), ("Direct Bilirubin", "bilirubin_direct"),
    ("Serum Albumin", "albumin"), ("Total Protein", "total_protein"),
    ("TSH", "tsh"), ("Free T4", "free_t4"), ("FT3", "free_t3"),
    ("Serum Sodium", "sodium"), ("K+", "potassium"), ("HCO3", "bicarbonate"),
    ("Total CO2", "bicarbonate"), ("PCV", "hematocrit"),
    ("Packed Cell Volume", "hematocrit"), ("Total Leucocyte Count", "wbc"),
    ("Polymorphs", "neutrophils"), ("RDW-CV", "rdw"),
    ("Mean Corpuscular Haemoglobin", "mch"),
])
def test_common_printed_labels_resolve(label, expected):
    assert canonical_analyte(label) == expected


def test_an_unknown_label_still_returns_none_rather_than_a_guess():
    assert canonical_analyte("Serum Rhubarb") is None


# --- an analyte name containing a digit is not split at the digit ---
@pytest.mark.parametrize("line,label,value", [
    ("HbA1c 6.2 % 4.0 - 5.6", "HbA1c", 6.2),
    ("Free T4 1.2 ng/dL 0.8 - 1.8", "Free T4", 1.2),
    ("Free T3 3.1 pg/mL 2.3 - 4.2", "Free T3", 3.1),
    ("CO2 22 mmol/L 22 - 29", "CO2", 22.0),
    ("Vitamin B12 220 pg/mL", "Vitamin B12", 220.0),
])
def test_a_digit_inside_an_analyte_name_is_not_a_value(line, label, value):
    """``HbA1c 6.2 %`` once read as the analyte 'HbA' with the value 1 and the
    unit 'c'. A label and a value are separated by a separator, not by the
    first digit that appears.
    """
    raw = extract_raw_values(line + "\n")
    assert len(raw) == 1
    assert raw[0].label == label
    assert raw[0].value == value


# --- end to end over the panels this phase adds --------------------
_PANELS = {
    ReportType.KIDNEY_FUNCTION: [
        ("S. Creatinine 1.6 mg/dL 0.6 - 1.2 H", "creatinine", 141.472),
        ("Blood Urea 58 mg/dL 15 - 40 H", "urea", 9.657),
        ("eGFR 46 mL/min/1.73m2", "egfr", 46.0),
    ],
    ReportType.LIVER_FUNCTION: [
        ("SGPT (ALT) 78 U/L 0 - 40 H", "alt", 78.0),
        ("Total Bilirubin 1.9 mg/dL 0.2 - 1.2 H", "bilirubin_total", 32.4976),
        ("Serum Albumin 3.1 g/dL 3.5 - 5.0 L", "albumin", 31.0),
    ],
    ReportType.THYROID: [
        ("TSH 8.4 uIU/mL 0.4 - 4.0 H", "tsh", 8.4),
        ("Free T4 0.7 ng/dL 0.8 - 1.8 L", "free_t4", 9.009),
    ],
    ReportType.ELECTROLYTES: [
        ("Serum Sodium 128 mEq/L 136 - 145 L", "sodium", 128.0),
        ("Serum Calcium 8.2 mg/dL 8.6 - 10.2 L", "calcium", 2.0459),
    ],
}


@pytest.mark.parametrize(
    "report_type,line,analyte,normalised",
    [(rt, line, analyte, value)
     for rt, rows in _PANELS.items() for line, analyte, value in rows],
)
def test_a_panel_line_survives_extraction_normalisation_and_validation(
    report_type, line, analyte, normalised
):
    schema = get_schema(report_type)
    raw = extract_raw_values(line + "\n")[0]
    value = validate_value(raw, schema=schema)

    assert value.analyte == analyte, value.issues
    assert value.status is ValueStatus.OBSERVED, value.issues
    assert value.normalized.convertible
    assert value.normalized.value == pytest.approx(normalised)
    assert value.normalized.unit == CANONICAL_UNIT[analyte]
