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


# --- the result column first, the reference range after it ----------
#
# Found on a real report: every lipid result was lost. The line
#
#     Total Cholesterol 228 mg/dL < 200 mg/dL
#
# was read as a censored result, because the censored rule - added to stop
# "TSH <0.01" becoming 0.01 - won unconditionally and its label pattern
# accepts digits. So the label swallowed "Total Cholesterol 228 mg/dL" and the
# clinical target was reported as the result. The fix for one real failure
# mode had created another.
#
# The invariant now: which shape the line is depends on where the bound sits.
# Before the value it IS the result; after it, it is the reference range.


def _first(line):
    values = extract_raw_values(line)
    return values[0] if values else None


class TestABoundThatIsTheResult:
    """Must stay censored: no number, and the text kept verbatim."""

    def test_a_bare_censored_result(self):
        raw = _first("TSH <0.01")
        assert raw.value is None
        assert raw.value_text == "<0.01"

    def test_a_censored_result_with_a_separator_and_spaces(self):
        raw = _first("TSH: < 0.01")
        assert raw.value is None
        assert raw.value_text == "<0.01"

    def test_a_censored_result_that_also_prints_a_reference_range(self):
        """The comparator survives into the structured value, and the range
        beside it is read as a range."""
        raw = _first("TSH < 0.01 uIU/mL 0.4 - 4.0")
        assert raw.value is None
        assert raw.value_text == "<0.01"
        assert raw.unit == "uIU/mL"
        assert raw.reference_text == "0.4 - 4.0"

    def test_an_upper_censored_result(self):
        raw = _first("Vitamin B12 > 2000 pg/mL 200 - 900")
        assert raw.value is None
        assert raw.value_text == ">2000"

    def test_a_bound_with_no_analyte_yields_nothing_rather_than_a_number(self):
        assert extract_raw_values("<0.01") == []


class TestABoundThatIsTheReferenceRange:
    """The result keeps its value; the bound is the range."""

    def test_a_one_sided_target_after_the_result(self):
        raw = _first("Total Cholesterol 228 mg/dL < 200 mg/dL")
        assert raw.value == 228.0
        assert raw.unit == "mg/dL"
        assert raw.reference_text == "< 200 mg/dL"

    def test_an_at_least_target_after_the_result(self):
        raw = _first("HDL Cholesterol 38 mg/dL \u2265 40 mg/dL")
        assert raw.value == 38.0
        assert raw.reference_text == "\u2265 40 mg/dL"

    def test_a_one_sided_target_with_no_unit_in_the_range(self):
        raw = _first("Total Cholesterol 228 mg/dL < 200")
        assert raw.value == 228.0
        assert parse_reference_range(raw.reference_text).high == 200.0

    def test_result_and_bound_with_no_unit_at_all(self):
        raw = _first("Cholesterol 5.4 <200")
        assert raw.value == 5.4
        assert raw.reference_text == "<200"

    def test_result_and_an_interval_with_no_unit_at_all(self):
        """A dash-range is a range, not a competing second number."""
        raw = _first("Cholesterol 5.4 3-10")
        assert raw.value == 5.4
        assert parse_reference_range(raw.reference_text).low == 3.0


class TestTheSecondNumberGuardStillHolds:
    """Relaxing it for intervals must not reopen what it was built for."""

    def test_an_ocr_split_number_still_yields_no_value(self):
        raw = _first("Hemoglobin 1 3.4 g/dL")
        assert raw.value is None

    def test_two_results_on_one_line_still_yield_no_value(self):
        raw = _first("Bilirubin 1.2 / 1.4")
        assert raw.value is None


# --- a range may print its own unit ---------------------------------
class TestAReferenceRangeThatCarriesItsUnit:
    """Indian reports print the unit in the range column. The parser was
    anchored and read none of them, so nine correctly extracted results on a
    real report could not be interpreted."""

    def test_an_interval_with_a_trailing_unit(self):
        ref = parse_reference_range("13.5 - 17.5 g/dL")
        assert (ref.low, ref.high, ref.kind) == (13.5, 17.5, "interval")
        assert ref.unit == "g/dL"

    def test_an_interval_with_the_unit_on_both_ends(self):
        ref = parse_reference_range("13.5 g/dL - 17.5 g/dL")
        assert (ref.low, ref.high) == (13.5, 17.5)
        assert ref.unit == "g/dL"

    def test_an_interval_whose_ends_disagree_is_unparsed(self):
        """Not resolved by picking one of them."""
        assert parse_reference_range("13.5 g/dL - 17.5 g/L").kind == "unparsed"

    def test_an_upper_bound_with_a_unit(self):
        ref = parse_reference_range("< 200 mg/dL")
        assert (ref.high, ref.kind, ref.unit) == (200.0, "upper_bound", "mg/dL")

    def test_a_lower_bound_with_a_unit(self):
        ref = parse_reference_range("\u2265 40 mg/dL")
        assert (ref.low, ref.kind, ref.unit) == (40.0, "lower_bound", "mg/dL")

    def test_a_cell_count_unit_on_the_range(self):
        ref = parse_reference_range("150 - 450 10^9/L")
        assert (ref.low, ref.high, ref.unit) == (150.0, 450.0, "10^9/L")

    def test_a_per_volume_unit_on_the_range(self):
        ref = parse_reference_range("4000 - 11000 /\u00b5L")
        assert (ref.low, ref.high, ref.unit) == (4000.0, 11000.0, "/\u00b5L")

    def test_a_range_with_no_unit_still_parses_and_reports_none(self):
        ref = parse_reference_range("13.5 - 17.5")
        assert (ref.low, ref.high) == (13.5, 17.5)
        assert ref.unit == ""

    def test_a_unit_pattern_can_never_swallow_the_other_end_of_a_range(self):
        for text in ("10 - 20", "0.4 - 4.0", "150 - 450"):
            ref = parse_reference_range(text)
            assert ref.kind == "interval", text
            assert ref.unit == "", text


def test_a_range_printed_with_thousands_separators():
    """"4,000 - 11,000 /uL" is how a white-cell range is printed, and it was
    the last thing stopping a correctly extracted WBC from being usable."""
    ref = parse_reference_range("4,000 - 11,000 /\u00b5L")
    assert (ref.low, ref.high, ref.unit) == (4000.0, 11000.0, "/\u00b5L")


def test_a_decimal_comma_is_not_read_as_a_thousands_separator():
    """"1,5 - 4,5" would be 15 and 45. Left unparsed instead."""
    assert parse_reference_range("1,5 - 4,5").kind == "unparsed"
