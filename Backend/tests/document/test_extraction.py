"""Line-level extraction and reference-range parsing.

The rule under test everywhere: a line that cannot be parsed cleanly is
skipped, and a reference range that is not a numeric interval is admitted as
such rather than turned into invented bounds.
"""
from __future__ import annotations

from intelligence.document.extraction import extract_raw_values, parse_reference_range


# --- reference ranges ------------------------------------------------
def test_a_plain_interval_is_parsed():
    ref = parse_reference_range("0 - 6")
    assert (ref.low, ref.high, ref.kind) == (0.0, 6.0, "interval")
    assert ref.is_numeric


def test_unicode_dashes_and_decimals_are_handled():
    ref = parse_reference_range("13.0 – 17.0")
    assert (ref.low, ref.high) == (13.0, 17.0)


def test_an_upper_bound_is_kept_as_an_upper_bound():
    ref = parse_reference_range("< 200")
    assert ref.high == 200.0 and ref.low is None and ref.kind == "upper_bound"


def test_a_lower_bound_is_kept_as_a_lower_bound():
    ref = parse_reference_range("> 40")
    assert ref.low == 40.0 and ref.high is None and ref.kind == "lower_bound"


def test_up_to_phrasing_is_an_upper_bound():
    assert parse_reference_range("Up to 6").high == 6.0


def test_a_qualitative_range_is_not_forced_into_numbers():
    ref = parse_reference_range("Negative")
    assert ref.kind == "qualitative" and ref.low is None and ref.high is None


def test_an_unparseable_range_says_so():
    ref = parse_reference_range("consult physician")
    assert ref.kind == "unparsed"
    assert not ref.is_numeric


def test_a_reversed_interval_is_ordered():
    ref = parse_reference_range("17 - 13")
    assert (ref.low, ref.high) == (13.0, 17.0)


# --- line extraction -----------------------------------------------
def test_a_standard_result_line_is_pulled_apart():
    rows = extract_raw_values("Hemoglobin        13.4 g/dL     13.0 - 17.0\n")
    assert len(rows) == 1
    row = rows[0]
    assert row.label == "Hemoglobin"
    assert row.value == 13.4
    assert row.unit == "g/dL"
    assert row.reference_text == "13.0 - 17.0"
    assert row.printed_flag == ""
    assert row.char_span[0] < row.char_span[1]


def test_a_cell_count_unit_is_recognised():
    rows = extract_raw_values("WBC   7.2   10^9/L   4.0 - 11.0\n")
    assert rows[0].unit == "10^9/L"
    assert rows[0].reference_text == "4.0 - 11.0"


def test_a_printed_high_flag_is_captured_wherever_it_sits():
    after = extract_raw_values("Glucose  126  mg/dL  70 - 99  H\n")[0]
    between = extract_raw_values("Glucose  126  mg/dL  H  70 - 99\n")[0]
    assert after.printed_flag == "H" and after.reference_text == "70 - 99"
    assert between.printed_flag == "H" and between.reference_text == "70 - 99"


def test_a_value_with_thousands_separators_is_parsed():
    row = extract_raw_values("Platelet Count  2,40,000  /uL  150000 - 450000\n")[0]
    assert row.value == 240000.0


def test_metadata_lines_are_not_mistaken_for_results():
    text = (
        "Patient Age: 54 Years\n"
        "Page 1 of 3\n"
        "Sample Collected: 2024-05-01 09:00\n"
        "Lab No 12345678\n"
        "Hemoglobin  13.4 g/dL  13.0 - 17.0\n"
    )
    rows = extract_raw_values(text)
    assert [r.label for r in rows] == ["Hemoglobin"]


def test_all_caps_section_headings_are_skipped():
    rows = extract_raw_values("COMPLETE BLOOD COUNT\nHemoglobin 13.4 g/dL\n")
    assert [r.label for r in rows] == ["Hemoglobin"]


def test_a_non_numeric_value_line_is_not_extracted_as_a_number():
    rows = extract_raw_values("Blood Group   O Positive\n")
    # "O Positive" has no leading number, so nothing is extracted rather than a
    # guess.
    assert rows == []


def test_a_line_with_no_unit_records_the_gap():
    row = extract_raw_values("Random Value   42\n")[0]
    assert row.unit == ""
    assert "no unit on the line" in row.issues
    assert row.extraction_confidence < 0.85


def test_page_breaks_map_a_span_to_its_page():
    text = "Hemoglobin 13.4 g/dL\n" + "X" * 50 + "\nWBC 7.2 10^9/L\n"
    # a page break just before the WBC line
    brk = text.index("WBC")
    rows = extract_raw_values(text, page_breaks=[brk])
    pages = {r.label: r.page for r in rows}
    assert pages["Hemoglobin"] == 1
    assert pages["WBC"] == 2
