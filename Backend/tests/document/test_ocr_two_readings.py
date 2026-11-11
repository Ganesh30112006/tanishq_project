"""A scanned number is trusted when two different readings of the page agree.

Found on 2026-11-08: OCR read a range of 4.5-5.5 as 45-55, which calls a normal value
low, and a single-reading confidence limit was throwing away correct numbers.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import OcrOutcome, OcrResult, ValueStatus
from intelligence.document.ocr.provider import OcrRequest
from intelligence.document.pipeline import process_document

HEADER = "COMPLETE BLOOD COUNT\nTest Result Unit Reference\nHaemoglobin count report\n"


class Reader:
    name = "fake"

    def __init__(self, first: str, second: str | None, spans=(), second_spans=()):
        self.first, self.second_text, self.spans, self.second_spans = first, second, spans, second_spans

    def is_available(self) -> bool:
        return True

    def run(self, request: OcrRequest) -> OcrResult:
        second = None
        if self.second_text is not None:
            second = OcrResult(
                outcome=OcrOutcome.OK, provider="fake", text=HEADER + self.second_text,
                mean_confidence=0.9, word_spans=_spans(HEADER + self.second_text, self.second_spans),
            )
        return OcrResult(
            outcome=OcrOutcome.OK, provider="fake", text=HEADER + self.first, mean_confidence=0.9,
            word_spans=_spans(HEADER + self.first, self.spans), second=second,
        )


def _spans(text: str, words) -> tuple:
    return tuple((text.index(word), text.index(word) + len(word), confidence) for word, confidence in words)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def read(reader: Reader):
    return process_document(PNG, declared_type="image/png", ocr_provider=reader)


def observed(result) -> dict:
    return {r.value.analyte: r.value.value for r in result.values if r.value.status is ValueStatus.OBSERVED}


def reasons(result) -> set[str]:
    return {r.value.reason for r in result.values}


LINE = "Haemoglobin 13.4 g/dL 12.0 - 15.0"


def test_agreement_lifts_a_number_the_first_reading_was_unsure_of():
    result = read(Reader(LINE, LINE, spans=[("13.4", 0.75)]))
    assert observed(result) == {"hemoglobin": 13.4}


def test_one_reading_alone_still_has_to_be_sure():
    result = read(Reader(LINE, None, spans=[("13.4", 0.75)]))
    assert observed(result) == {}
    assert "ocr_number_uncertain" in reasons(result)


def test_agreement_does_not_rescue_a_number_that_is_barely_read():
    result = read(Reader(LINE, LINE, spans=[("13.4", 0.30)], second_spans=[("13.4", 0.30)]))
    assert observed(result) == {}


def test_different_numbers_mean_neither_is_used_however_sure_each_is():
    result = read(Reader(LINE, "Haemoglobin 18.4 g/dL 12.0 - 15.0", spans=[("13.4", 0.99)]))
    assert observed(result) == {}
    assert "ocr_readings_disagree" in reasons(result)


def test_a_misread_range_is_caught_because_it_changes_the_result_s_place():
    result = read(Reader("Haemoglobin 13.4 g/dL 120 - 150", LINE))
    assert observed(result) == {}
    assert "ocr_readings_disagree" in reasons(result)


def test_the_second_reading_recovers_a_unit_the_first_lost():
    result = read(Reader("Haemoglobin 13.4 g/ 12.0 - 15.0", LINE))
    assert observed(result) == {"hemoglobin": 13.4}


def test_the_recovered_value_points_at_the_words_it_came_from():
    result = read(Reader("Haemoglobin 13.4 g/ 12.0 - 15.0", LINE))
    record = next(r for r in result.values if r.value.status is ValueStatus.OBSERVED)
    start, end = record.provenance.char_span
    assert result.text[start:end] == LINE


def test_the_second_reading_cannot_replace_the_first_with_a_different_number():
    result = read(Reader("Haemoglobin 18.4 g/ 12.0 - 15.0", LINE))
    assert observed(result) == {}


def test_a_test_only_the_second_reading_saw_must_be_sure_on_its_own():
    other = "Haemoglobin 13.4 g/dL 12.0 - 15.0\nPlatelet Count 245 10^9/L 150 - 410"
    unsure = read(Reader(LINE, other, second_spans=[("245", 0.70)]))
    assert "platelets" not in observed(unsure)
    sure = read(Reader(LINE, other, second_spans=[("245", 0.97)]))
    assert observed(sure)["platelets"] == 245.0


def test_with_no_second_reading_nothing_changes():
    assert observed(read(Reader(LINE, None))) == {"hemoglobin": 13.4}


@pytest.mark.parametrize("second", ["", "nothing useful here"])
def test_a_second_reading_with_no_values_takes_nothing_away(second):
    assert observed(read(Reader(LINE, second))) == {"hemoglobin": 13.4}


def test_colour_is_removed_only_when_asked():
    np = pytest.importorskip("numpy")
    from PIL import Image, ImageDraw

    from intelligence.document.ocr import preprocess

    page = Image.new("RGB", (900, 1200), (255, 255, 255))
    draw = ImageDraw.Draw(page)
    draw.rectangle((100, 100, 300, 140), fill=(0, 0, 0))     # black print
    draw.rectangle((100, 300, 300, 340), fill=(200, 0, 0))   # a result printed in red
    assert preprocess.has_colour(page)

    kept = np.asarray(preprocess.prepare(page))
    dropped = np.asarray(preprocess.prepare(page, drop_colour=True))
    scale = kept.shape[0] / 1200
    red_y, red_x = int(320 * scale), int(200 * scale)
    black_y = int(120 * scale)
    assert kept[red_y, red_x] < 120, "the first reading must keep a result printed in red"
    assert dropped[black_y, red_x] < 60, "black print stays in both"
    assert dropped[red_y, red_x] > kept[red_y, red_x]
    assert not preprocess.has_colour(Image.new("L", (100, 100), 255))


# --- what agreement cannot do, and the guards for it ----------------------------

def test_a_zero_is_not_believed_even_when_both_readings_agree():
    # A watermark over "30.0" gives 0.0 in every reading of that picture.
    line = "AST (SGOT) 0.0 U/L 15.00 - 40.00"
    assert observed(read(Reader(line, line))) == {}


def test_a_zero_is_believed_for_a_test_that_can_really_be_zero():
    line = "Basophils 0 % 0 - 2"
    assert observed(read(Reader(line, line))) == {"basophils": 0.0}


def test_an_abnormal_number_seen_by_one_reading_is_held_but_still_warned_about():
    line = "Haemoglobin 7.1 g/dL 12.0 - 15.0"
    result = read(Reader(line, "nothing useful here"))
    assert observed(result) == {}
    held = next(r.value for r in result.values if r.value.printed_label == "Haemoglobin")
    assert held.reason == "ocr_number_uncertain"
    assert held.reference_status.value == "BELOW_REFERENCE_RANGE"


def test_an_abnormal_number_both_readings_saw_is_used():
    line = "Haemoglobin 7.1 g/dL 12.0 - 15.0"
    assert observed(read(Reader(line, line))) == {"hemoglobin": 7.1}


def test_an_abnormal_number_only_the_second_reading_saw_is_held_but_kept_visible():
    other = "Haemoglobin 13.4 g/dL 12.0 - 15.0\nPlatelet Count 45 10^9/L 150 - 410"
    result = read(Reader(LINE, other, second_spans=[("45", 0.99)]))
    assert "platelets" not in observed(result)
    assert any(r.value.printed_label == "Platelet Count" and r.value.reference_status.value == "BELOW_REFERENCE_RANGE"
               for r in result.values)


class StampReader(Reader):
    def __init__(self, first, second, stamp_free):
        super().__init__(first, second)
        self.stamp_free_text = stamp_free

    def run(self, request):
        result = super().run(request)
        result.stamp_free = OcrResult(
            outcome=OcrOutcome.OK, provider="fake", text=HEADER + self.stamp_free_text, mean_confidence=0.9,
        )
        return result


def test_the_colour_free_reading_cannot_overrule_the_others():
    assert observed(read(StampReader(LINE, LINE, "Haemoglobin 18.4 g/dL 12.0 - 15.0"))) == {"hemoglobin": 13.4}


def test_the_colour_free_reading_can_recover_a_value_a_stamp_hid():
    assert observed(read(StampReader("Haemoglobin 13.4 g/ 12.0 - 15.0", "nothing", LINE))) == {"hemoglobin": 13.4}


def test_the_colour_free_reading_counts_as_agreement():
    line = "Haemoglobin 7.1 g/dL 12.0 - 15.0"
    assert observed(read(StampReader(line, "nothing", line))) == {"hemoglobin": 7.1}


def test_a_flag_read_as_a_digit_is_held_even_when_both_readings_agree():
    # Found on 2026-11-08: "Blood Urea 48 ↑" read as 481 by every reading.
    line = "Blood Urea 481 mg/dL 10 - 40"
    result = read(Reader(line, line))
    assert observed(result) == {}
    held = next(r.value for r in result.values if r.value.printed_label == "Blood Urea")
    assert held.reason == "ocr_number_uncertain"
    assert held.reference_status.value == "ABOVE_REFERENCE_RANGE", "the patient is still warned"


def test_a_high_result_within_reason_is_used():
    line = "Blood Urea 96 mg/dL 10 - 40"
    assert observed(read(Reader(line, line))) == {"urea": 96.0}


def test_a_far_outside_result_on_a_typed_pdf_is_not_affected():
    from intelligence.document.extraction.analytes import extract_raw_values
    from intelligence.document.validation.checks import validate_value

    [raw] = extract_raw_values("Blood Urea 481 mg/dL 10 - 40")
    assert validate_value(raw).status is ValueStatus.OBSERVED


# --- a row is judged by its own words, not the page's average -------------------

class Cluttered(Reader):
    """A page whose average is pulled down, or up, by what is printed around the table."""

    def __init__(self, first: str, spans, page_mean: float):
        super().__init__(first, None, spans=spans)
        self.page_mean = page_mean

    def run(self, request: OcrRequest) -> OcrResult:
        done = super().run(request)
        return OcrResult(
            outcome=OcrOutcome.LOW_CONFIDENCE if self.page_mean < 0.55 else OcrOutcome.OK,
            provider="fake", text=done.text, mean_confidence=self.page_mean, word_spans=done.word_spans,
        )


def test_a_clean_row_on_a_cluttered_page_is_used():
    # Found on 2026-11-08: a QR code and a web page around a clean table gave a page
    # mean of 0.39, and every result on it was refused.
    sure = [(w, 0.97) for w in ("Haemoglobin", "13.4", "g/dL", "12.0", "15.0")]
    result = read(Cluttered(LINE, sure, page_mean=0.39))
    assert observed(result) == {"hemoglobin": 13.4}
    assert any(i.code == "OCR_LOW_CONFIDENCE" for i in result.issues)


def test_a_garbled_row_on_a_clean_page_is_not_used():
    shaky = [("Haemoglobin", 0.31), ("13.4", 0.96), ("g/dL", 0.22), ("12.0", 0.40), ("15.0", 0.35)]
    result = read(Cluttered(LINE, shaky, page_mean=0.92))
    assert observed(result) == {}
    assert "ocr_below_confidence_floor" in reasons(result)
