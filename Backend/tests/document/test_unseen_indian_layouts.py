"""Row layouts found on Indian sample reports the reader had never seen (2026-11-08).

The rows the laboratory marked abnormal were among those lost, so a report could
read as nothing out of range. Each new shape has a matching refusal below: a row
that only nearly fits must still give no number.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import ReferenceStatus, ValueStatus
from intelligence.document.extraction.analytes import extract_raw_values
from intelligence.document.normalization.units import normalize_value
from intelligence.document.validation.checks import validate_value


def read(line: str):
    rows = extract_raw_values(line)
    assert len(rows) == 1, rows
    return rows[0], validate_value(rows[0])


# --- result, optional flag, range, then unit --------------------------------

@pytest.mark.parametrize(
    ("line", "analyte", "value", "unit", "low", "high"),
    [
        ("Haemoglobin 15 11.5 - 18.0 gm%", "hemoglobin", 15.0, "gm%", 11.5, 18.0),
        ("Total WBC count 9000 4000-11000 cumm", "wbc", 9000.0, "cumm", 4000.0, 11000.0),
        ("Total RBC count 5.2 4.5 - 5.5 mill/cumm", "rbc", 5.2, "mill/cumm", 4.5, 5.5),
        ("Eosinophils 1 00 - 06 %", "eosinophils", 1.0, "%", 0.0, 6.0),
        ("Total Cholesterol 150 0 - 200 mg/dl", "cholesterol", 150.0, "mg/dl", 0.0, 200.0),
    ],
)
def test_range_before_unit_is_read(line, analyte, value, unit, low, high):
    _, checked = read(line)
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert (checked.analyte, checked.value, checked.unit) == (analyte, value, unit)
    assert (checked.reference.low, checked.reference.high) == (low, high)


def test_a_one_sided_range_before_the_unit_is_read():
    _, checked = read("Cholesterol, Total 228 < 200 mg/dL")
    assert checked.value == 228.0
    assert checked.unit == "mg/dL"
    assert checked.reference_status is ReferenceStatus.ABOVE


@pytest.mark.parametrize(
    ("line", "flag", "status"),
    [
        ("Hemoglobin (Hb) 12.5 Low 13.0 - 17.0 g/dL", "L", ReferenceStatus.BELOW),
        ("TOTAL PROTEINS 8.5 H 6.2 - 8.0 gm/dL", "H", ReferenceStatus.ABOVE),
    ],
)
def test_flag_between_result_and_range_is_kept(line, flag, status):
    _, checked = read(line)
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert checked.printed_flag == flag
    assert checked.reference_status is status


def test_borderline_is_a_remark_and_never_taken_as_the_unit():
    _, checked = read("Platelet Count 150000 Borderline 150000 - 410000 cumm")
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert checked.unit == "cumm"
    assert checked.printed_flag == "BORDERLINE"


def test_a_range_flag_that_contradicts_the_range_is_held():
    _, checked = read("TOTAL PROTEINS 7.0 H 6.2 - 8.0 gm/dL")
    assert checked.status is ValueStatus.NEEDS_REVIEW


@pytest.mark.parametrize(
    "line",
    [
        # OCR split one number in two: which is the result is unknown.
        "Hemoglobin 1 3.4 g/dL",
        # Two results, then a range.
        "Hemoglobin 13.4 12.9 11.0 - 15.0 g/dL",
        # No dash, so this is not plainly a range.
        "Hemoglobin 13.4 11.0 15.0 g/dL",
        # A word that is not a flag sits where the flag would.
        "Hemoglobin 13.4 repeat 11.0 - 15.0 g/dL",
        # Ranges by age: which band applies is not for this line to decide.
        "Thyroid Stimulating Hormone (TSH) 4 0.37 - 6.00 : 6 Yrs - 18 Yrs mIU/L",
    ],
)
def test_a_row_that_only_nearly_fits_is_not_observed(line):
    for row in extract_raw_values(line):
        assert validate_value(row).status is not ValueStatus.OBSERVED, row


def test_a_blank_result_does_not_borrow_the_low_end_of_its_range():
    for row in extract_raw_values("Hemoglobin 12.0 - 15.0 g/dL"):
        assert validate_value(row).status is not ValueStatus.OBSERVED, row


def test_a_result_that_cannot_fit_its_range_is_refused():
    # Printed on a real sample: 2.4 in lakhs, against a range per cubic millimetre.
    _, checked = read("Platelet Count 2.4 150000 - 410000 /cumm")
    assert checked.status is ValueStatus.INVALID


# --- a flag beside the name -------------------------------------------------

@pytest.mark.parametrize(
    ("line", "analyte", "value", "flag", "status"),
    [
        ("LYMPHOCYTE L 18 % 20 - 40", "lymphocytes", 18.0, "L", ReferenceStatus.BELOW),
        ("MONOCYTES L 1 % 2 - 10", "monocytes", 1.0, "L", ReferenceStatus.BELOW),
        ("MEAN CELL HAEMOGLOBIN CON, MCHC H 35.7 % 31.5 - 34.5", "mchc", 35.7, "H", ReferenceStatus.ABOVE),
    ],
)
def test_the_rows_a_lab_marks_abnormal_are_read(line, analyte, value, flag, status):
    _, checked = read(line)
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert (checked.analyte, checked.value, checked.printed_flag) == (analyte, value, flag)
    assert checked.reference_status is status


def test_the_flag_is_only_taken_from_beside_a_known_test():
    row, checked = read("Something L 18 % 20 - 40")
    assert row.label == "Something L"
    assert checked.analyte is None


# --- name, unit, range and method, then result ------------------------------

@pytest.mark.parametrize(
    ("line", "analyte", "value", "unit", "flag"),
    [
        ("Hemoglobin g/dL 13.0 - 16.5Colorimetric 14.5", "hemoglobin", 14.5, "g/dL", ""),
        ("RBC Count million/cmm 4.5 - 5.5Electrical impedance 4.79", "rbc", 4.79, "million/cmm", ""),
        ("WBC Count H /cmm 4000 - 10000SF Cube cell analysis 10570", "wbc", 10570.0, "/cmm", "H"),
        ("Basophils % 0 - 2Microscopic 00", "basophils", 0.0, "%", ""),
    ],
)
def test_unit_first_row_takes_the_last_number(line, analyte, value, unit, flag):
    _, checked = read(line)
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert (checked.analyte, checked.value, checked.unit, checked.printed_flag) == (analyte, value, unit, flag)


@pytest.mark.parametrize(
    "line",
    [
        # Nothing between range and result: "16.514.5" can be split in many ways.
        "Hemoglobin g/dL 13.0 - 16.514.5",
        # No test name: an absolute count whose name is printed elsewhere.
        "/cmm 2000 - 67007716",
        # Not a test we know, so the range's number must not become its result.
        "Vitamin Z g/dL 13.0 - 16.5Colorimetric 14.5",
        # Not a unit we know.
        "Hemoglobin blorps 13.0 - 16.5Colorimetric 14.5",
    ],
)
def test_a_row_that_only_nearly_fits_unit_first_is_not_observed(line):
    for row in extract_raw_values(line):
        assert validate_value(row).status is not ValueStatus.OBSERVED, row


# --- units ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("analyte", "value", "unit", "expected"),
    [
        ("hemoglobin", 15.0, "gm%", 150.0),
        ("wbc", 5100.0, "cumm", 5.1),
        ("alt", 36.0, "U/I", 36.0),
        ("mchc", 35.7, "%", 357.0),
    ],
)
def test_new_units_convert(analyte, value, unit, expected):
    done = normalize_value(analyte, value, unit)
    assert done.convertible
    assert done.value == pytest.approx(expected)


@pytest.mark.parametrize(
    ("analyte", "unit"),
    [("wbc", "gm%"), ("rbc", "cumm"), ("hemoglobin", "U/I"), ("mcv", "%"), ("mch", "%")],
)
def test_new_units_do_not_spread_to_other_tests(analyte, unit):
    assert not normalize_value(analyte, 10.0, unit).convertible


# --- found on a second vendor's reports ------------------------------------------

def test_a_band_name_after_the_range_is_not_taken_for_a_unit():
    _, checked = read("Total Cholesterol 228 mg/dL < 200 Desirable")
    assert checked.status is ValueStatus.OBSERVED, checked.issues
    assert checked.reference_status is ReferenceStatus.ABOVE


def test_a_word_that_names_no_band_still_stops_the_range():
    _, checked = read("Total Cholesterol 228 mg/dL < 200 fasting")
    assert checked.status is not ValueStatus.OBSERVED


def test_post_lunch_sugar_and_tsh_in_mu_per_litre():
    _, sugar = read("Post Lunch Blood Sugar (PLBS) 212 mg/dL 80 - 140")
    assert (sugar.analyte, sugar.status) == ("random_glucose", ValueStatus.OBSERVED)
    _, tsh = read("TSH 8.9 mU/L 0.4 - 4.0")
    assert (tsh.analyte, tsh.status, tsh.reference_status) == ("tsh", ValueStatus.OBSERVED, ReferenceStatus.ABOVE)
