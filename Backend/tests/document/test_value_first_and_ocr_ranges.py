"""Result-first tables, names continued on the next line, and OCR's lost dashes.

Every one of these is a shape found on a real laboratory report. The numbers are
invented; the layouts are not. Most tests are about when a value must be refused.
"""
from __future__ import annotations

import pytest

from intelligence.document.classification.keyword import classify
from intelligence.document.classification.panels import headings, multi_panel
from intelligence.document.contracts import ClassificationStatus, ReportType
from intelligence.document.extraction import extract_raw_values
from intelligence.document.extraction.reference import parse_reference_range
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.validation import validate_value

HEADER = "Test Name Results Units Bio. Ref. Interval"


def _table(*rows: str) -> dict:
    return {r.label: r for r in extract_raw_values("\n".join([HEADER, *rows]))}


def _no_value(raws: dict) -> bool:
    return not any(r.value is not None for r in raws.values())


def test_a_result_stuck_to_its_name_is_read_with_the_range_below_it():
    got = _table("0.86Creatinine", "(Compensated Jaffes reaction, IDMS traceable)", " 0.67 - 1.17mg/dL")
    row = got["Creatinine"]
    assert row.value == 0.86
    assert row.unit == "mg/dL"
    assert row.reference_text == "0.67 - 1.17"
    assert "0.86Creatinine" in row.line and "0.67 - 1.17mg/dL" in row.line


def test_a_result_with_its_range_on_the_same_line_is_read():
    got = _table("11.00Urea Nitrogen  Blood 6.00 - 20.00mg/dL", "25.17TSH 0.35 - 5.50µIU/mL")
    assert got["Urea Nitrogen Blood"].value == 11.0
    assert got["Urea Nitrogen Blood"].reference_text == "6.00 - 20.00"
    assert got["TSH"].value == 25.17
    assert got["TSH"].unit == "µIU/mL"


def test_a_one_sided_range_closes_a_row():
    got = _table("21.4AST (SGOT)", "(IFCC without P5P)", "<50U/L")
    assert got["AST (SGOT)"].value == 21.4
    assert got["AST (SGOT)"].reference_text == "<50"


def test_a_range_with_a_space_before_its_unit_closes_a_row():
    got = _table("3.86Potassium", "(Indirect ISE)", " 3.50 - 5.10 mEq/L")
    assert got["Potassium"].value == 3.86
    assert got["Potassium"].unit == "mEq/L"


def test_a_blank_result_prints_no_number_and_borrows_none():
    """The sample with no results: the range's low end must not become the result."""
    assert _no_value(_table("Creatinine", "(Jaffe)", " 0.67 - 1.17mg/dL"))
    (raw,) = extract_raw_values(HEADER + chr(10) + "TSH, Ultrasensitive  0.550 - 4.780 µIU/mL")
    assert not validate_value(raw, schema=None, ocr_confidence=None).persists_clinical_value


def test_a_row_no_range_closes_is_not_read():
    got = _table("0.86Creatinine", "3.90Uric Acid", "(Uricase)", "3.50 - 7.20mg/dL")
    assert got["Creatinine"].value is None
    assert got["Uric Acid"].value == 3.9


def test_a_second_method_line_stops_the_row():
    assert _no_value(_table("0.86Creatinine", "(One)", "(Two)", "0.67 - 1.17mg/dL"))


def test_other_text_between_a_row_and_its_range_stops_the_row():
    assert _no_value(_table("0.86Creatinine", "Please correlate clinically", "0.67 - 1.17mg/dL"))


def test_a_range_without_a_unit_does_not_close_a_row():
    """Without a unit there is nothing to say what the number measures."""
    assert _no_value(_table("0.86Creatinine", "0.67 - 1.17"))


def test_a_unit_starting_with_a_digit_is_refused():
    """"11.010^9/L" could be 11.0 and 10^9/L, or 11.01 and 0^9/L. Neither is guessed."""
    assert _no_value(_table("7.8WBC", "4.0 - 11.010^9/L"))


def test_a_result_first_row_is_never_read_outside_the_table():
    raws = extract_raw_values("\n".join(["0.86Creatinine", "(Jaffe)", "0.67 - 1.17mg/dL"]))
    assert not any(r.value is not None for r in raws)


def test_a_result_first_table_ends_with_its_page():
    assert _no_value(_table("Page 1 of 2", "0.86Creatinine", "(Jaffe)", "0.67 - 1.17mg/dL"))


def test_a_row_cut_off_by_the_page_end_is_not_read():
    got = _table("0.86Creatinine", "Page 1 of 2", "0.67 - 1.17mg/dL")
    assert got["Creatinine"].value is None


def test_each_page_of_a_table_reopens_it():
    got = _table(
        "0.86Creatinine", "(Jaffe)", "0.67 - 1.17mg/dL", "Page 1 of 2",
        "Patient details here", HEADER,
        "140.00Sodium", "(Indirect ISE)", "136.00 - 146.00mEq/L",
    )
    assert got["Creatinine"].value == 0.86
    assert got["Sodium"].value == 140.0


def test_notes_in_the_table_are_not_rows():
    raws = _table("Note", "1. TSH levels vary by the time of day, between 2 - 4 a.m.", "3 months apart")
    assert _no_value(raws)


def test_a_package_a_long_note_makes_look_like_one_panel_is_still_a_package():
    """The lipid note out-votes everything; the headings say what the report is."""
    note = "\n".join(
        ["Treatment goals: LDL cholesterol, non-HDL cholesterol, triglycerides, lipid profile"] * 6
    )
    text = "\n".join([
        HEADER, "LIVER & KIDNEY PANEL, SERUM", "0.86Creatinine", "(Jaffe)", "0.67 - 1.17mg/dL",
        "LIPID SCREEN, SERUM", "250.70Cholesterol, Total", "(CHO-POD)", " <200.00mg/dL", note,
    ])
    classification = classify(text)
    assert classification.status is ClassificationStatus.CLASSIFIED
    assert classification.report_type is ReportType.LIPID_PROFILE
    assert set(multi_panel(text, classification, headings(text))) == {
        ReportType.LIPID_PROFILE, ReportType.LIVER_FUNCTION, ReportType.KIDNEY_FUNCTION,
    }


def test_a_single_panel_report_stays_a_single_panel_report():
    text = "\n".join([
        "LIPID PROFILE, SERUM", "Cholesterol 180 mg/dL < 200",
        "Triglycerides 120 mg/dL < 150", "HDL Cholesterol 50 mg/dL > 40",
        "LDL Cholesterol 90 mg/dL < 100",
    ])
    classification = classify(text)
    assert classification.status is ClassificationStatus.CLASSIFIED
    assert multi_panel(text, classification, headings(text)) == ()


# ------------------------------------------------- a name continued on the next line


def test_a_name_continued_after_the_result_is_joined():
    (row,) = extract_raw_values("Glycosylated 5.40 % <5.7\nHaemoglobin(Hb A1c)\n")
    assert row.value == 5.4
    assert canonical_analyte(row.label) == "hba1c"
    assert "Haemoglobin(Hb A1c)" in row.line


def test_the_ifcc_hba1c_is_not_joined_into_the_percentage():
    (row,) = extract_raw_values("Glycosylated 35.51 mmol/mol < 39.0\nHaemoglobin(Hb A1c) IFCC\n")
    assert canonical_analyte(row.label) is None


def test_a_name_already_known_is_never_extended_by_the_next_line():
    (row, *_) = extract_raw_values("Haemoglobin 11.0 g/dl\nModified cyanmethemoglobin\n")
    assert row.label == "Haemoglobin"
    assert "cyanmethemoglobin" not in row.line


def test_an_unrelated_next_line_is_not_joined():
    (row,) = extract_raw_values("Glycosylated 5.40 %\nPlease correlate clinically\n")
    assert row.label == "Glycosylated"


# -------------------------------------------------------------- OCR's lost dashes


def test_ocr_two_rising_numbers_are_a_range():
    got = parse_reference_range("12.0 15.0", dash_may_be_lost=True)
    assert (got.low, got.high, got.kind) == (12.0, 15.0, "interval")


@pytest.mark.parametrize("text", [
    "15.0 12.0",  # a dash lost from a range always leaves the low end first
    "15.0 15.0",
    "146",        # "1-6" read as one number: a misread, not a range
    "12.0 15.0 18.0",
])
def test_ocr_anything_else_stays_unparsed(text):
    assert parse_reference_range(text, dash_may_be_lost=True).kind == "unparsed"


def test_a_text_layer_keeps_two_numbers_unparsed():
    """A text layer does not lose dashes, so there two numbers are not a range."""
    assert parse_reference_range("12.0 15.0").kind == "unparsed"


def _validated(line: str, *, ocr_confidence: float | None):
    (raw,) = extract_raw_values(line)
    return validate_value(raw, schema=None, ocr_confidence=ocr_confidence)


def test_a_lost_dash_no_longer_holds_an_ocr_value_for_review():
    got = _validated("Haemoglobin 10.6 g/dl 12.0 15.0", ocr_confidence=0.9)
    assert got.status.value == "OBSERVED"
    assert got.reference.low == 12.0
    assert got.reference_status.value == "BELOW_REFERENCE_RANGE"


def test_a_misread_range_still_holds_an_ocr_value_for_review():
    got = _validated("Eosinophils 6.4 % 146", ocr_confidence=0.9)
    assert got.status.value == "NEEDS_REVIEW"


def test_two_numbers_on_a_text_layer_still_hold_a_value_for_review():
    got = _validated("Haemoglobin 10.6 g/dl 12.0 15.0", ocr_confidence=None)
    assert got.status.value == "NEEDS_REVIEW"


# ------------------------------------------------- OCR's confidence in one number


def _ocr_result(words: list[tuple[str, float]]):
    from intelligence.document.contracts import (
        BoundingBox,
        OcrOutcome,
        OcrResult,
        OcrToken,
    )
    from intelligence.document.ocr.local import _layout

    tokens = [
        OcrToken(
            text=word, page=1, confidence=conf,
            bbox=BoundingBox(page=1, x0=index / 100, y0=0.1, x1=(index + 1) / 100, y1=0.11),
        )
        for index, (word, conf) in enumerate(words)
    ]
    text, starts, spans = _layout(tokens)
    return OcrResult(
        outcome=OcrOutcome.OK, provider="test", tokens=tokens, text=text,
        mean_confidence=0.9, page_starts=starts, word_spans=spans,
    )


def test_word_spans_point_at_their_words():
    ocr = _ocr_result([("AST", 0.9), ("215", 0.86), ("U/L", 0.9)])
    assert [ocr.text[s:e] for s, e, _ in ocr.word_spans] == ["AST", "215", "U/L"]
    assert [c for _, _, c in ocr.word_spans] == [0.9, 0.86, 0.9]


def _confidence(words: list[tuple[str, float]]) -> float | None:
    from intelligence.document.pipeline import _number_confidence

    ocr = _ocr_result(words)
    (raw,) = extract_raw_values(ocr.text)
    return _number_confidence(ocr, raw)


def test_the_number_s_own_confidence_is_what_counts():
    assert _confidence([("AST", 0.99), ("215", 0.86), ("U/L", 0.99)]) == 0.86


def test_a_number_not_found_among_the_words_is_not_vouched_for():
    from intelligence.document.contracts import OcrOutcome, OcrResult
    from intelligence.document.pipeline import _number_confidence

    (raw,) = extract_raw_values("AST 215 U/L")
    ocr = OcrResult(
        outcome=OcrOutcome.OK, provider="test", text="AST 215 U/L",
        word_spans=((0, 3, 0.99), (8, 11, 0.99)),
    )
    assert _number_confidence(ocr, raw) == 0.0


def test_an_engine_that_gives_no_word_spans_is_not_refused_for_that():
    from intelligence.document.contracts import OcrOutcome, OcrResult
    from intelligence.document.pipeline import _number_confidence

    (raw,) = extract_raw_values("AST 215 U/L")
    assert _number_confidence(OcrResult(outcome=OcrOutcome.OK, provider="x", text="AST 215 U/L"), raw) is None


def test_an_uncertain_ocr_number_never_becomes_a_reading():
    """The misread that prompted this: right name, right unit, wrong number."""
    from intelligence.document.pipeline import process_document

    rows = [
        [("Liver", .99), ("Function", .99), ("Test", .99)],
        [("SGOT", .99), ("215", .86), ("U/L", .99)],
        [("SGPT", .99), ("31", .97), ("U/L", .99)],
    ]

    class Provider:
        name = "test"

        def is_available(self):
            return True

        def run(self, request):
            from intelligence.document.contracts import (
                BoundingBox,
                OcrOutcome,
                OcrResult,
                OcrToken,
            )
            from intelligence.document.ocr.local import _layout

            tokens = [
                OcrToken(
                    text=word, page=1, confidence=conf,
                    bbox=BoundingBox(page=1, x0=x / 10, y0=y / 10, x1=(x + 1) / 10, y1=y / 10 + 0.01),
                )
                for y, row in enumerate(rows)
                for x, (word, conf) in enumerate(row)
            ]
            text, starts, spans = _layout(tokens)
            return OcrResult(
                outcome=OcrOutcome.OK, provider="test", tokens=tokens, text=text,
                mean_confidence=0.96, page_starts=starts, word_spans=spans,
            )

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    result = process_document(png, declared_type="image/png", ocr_provider=Provider())
    uncertain = [r.value for r in result.values if r.provenance.source_text.startswith("SGOT")]
    assert uncertain and all(v.status.value == "AMBIGUOUS" and v.analyte is None for v in uncertain)
    assert uncertain[0].reason == "ocr_number_uncertain"
    assert {r.value.analyte: r.value.value for r in result.observed_values}.get("alt") == 31.0


# ------------------------------------------------------- rebuilding OCR's lines


def _placed(word: str, x: float, y: float, height: float = 0.012):
    from intelligence.document.contracts import BoundingBox, OcrToken

    return OcrToken(
        text=word, page=1, confidence=0.99,
        bbox=BoundingBox(page=1, x0=x, y0=y, x1=x + 0.05, y1=y + height),
    )


def test_a_row_across_the_old_band_edge_stays_one_line():
    """0.0499 and 0.0501 fell in different fixed bands, and the result left its name."""
    from intelligence.document.ocr.local import _layout

    text, _, _ = _layout([
        _placed("Creatinine", 0.1, 0.0499), _placed("0.86", 0.4, 0.0501), _placed("mg/dL", 0.6, 0.0499),
    ])
    assert text == "Creatinine 0.86 mg/dL"


def test_neighbouring_rows_are_never_merged():
    """A value joined to the row above would be the worst error this could make."""
    from intelligence.document.ocr.local import _layout

    text, _, _ = _layout([
        _placed("Haemoglobin", 0.1, 0.100), _placed("11.8", 0.4, 0.100),
        _placed("MCV", 0.1, 0.116), _placed("86.9", 0.4, 0.116),
    ])
    assert text.splitlines() == ["Haemoglobin 11.8", "MCV 86.9"]


def test_words_in_a_line_read_left_to_right_whatever_order_they_arrive():
    from intelligence.document.ocr.local import _layout

    text, _, _ = _layout([_placed("mg/dL", 0.6, 0.1), _placed("Urea", 0.1, 0.1), _placed("25", 0.4, 0.1)])
    assert text == "Urea 25 mg/dL"


def test_the_floor_sits_above_both_known_misreads():
    from intelligence.document.pipeline import OCR_NUMBER_FLOOR

    assert 0.93 < OCR_NUMBER_FLOOR <= 0.95  # the known misreads, and most correct numbers
