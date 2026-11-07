"""Health-check packages, cumulative reports and scanned PDFs.

Fourteen sample reports that Indian laboratories publish were run through the
reader on 2026-11-02. Nine were multi-panel health checks and yielded nothing,
two printed several dates' results on each row and yielded nothing, and a
scanned PDF could never be read at all. These pin how each is now read - and,
for each, the shapes that must still be refused.

Documents are built here, in memory. Nothing in this file is a label.
"""
from __future__ import annotations

import io
import sys
from datetime import date

import pytest

from intelligence.document.classification import classify
from intelligence.document.contracts import (
    BoundingBox,
    ClassificationStatus,
    DocumentMediaType,
    OcrOutcome,
    OcrToken,
    ReportType,
    ValueStatus,
)
from intelligence.document.extraction import extract_raw_values
from intelligence.document.extraction.cumulative import parse_dates
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.ocr.local import LocalTesseractProvider, _join
from intelligence.document.ocr.provider import OcrRequest
from intelligence.document.pipeline import Disposition, process_document


def _pdf(*pages: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(595, 842))
    for lines in pages:
        c.setFont("Helvetica", 9)
        y = 810
        for line in lines:
            c.drawString(30, y, line)
            y -= 13
        c.showPage()
    c.save()
    return buffer.getvalue()


def _read(pdf: bytes):
    return process_document(pdf, declared_type="application/pdf")


def _observed(result) -> dict[str, float]:
    return {
        r.value.analyte: r.value.value
        for r in result.values
        if r.value.status is ValueStatus.OBSERVED
    }


def _by_label(result, label: str):
    return [r for r in result.values if r.value.printed_label == label]


HEALTH_CHECK = (
    [
        "Laboratory Investigation Report",
        "Patient Name : Mr Test Age : 45 Years",
        "Hemoglobin 13.0 g/dL",
        "Lipid Profile, Serum",
        "Cholesterol 182 mg/dL < 200",
        "HDL Cholesterol 46 mg/dL > 40",
        "LDL Cholesterol 110 mg/dL < 130",
        "Triglycerides 130 mg/dL < 150",
        "Liver Function Test (LFT), Serum",
        "SGPT (ALT) 32 U/L 5 - 41",
        "SGOT (AST) 28 U/L 5 - 40",
        "Bilirubin Total 0.8 mg/dL 0.3 - 1.2",
        "Alkaline Phosphatase 90 U/L 40 - 129",
    ],
    [
        "Kidney Function Test (KFT)",
        "Creatinine 0.9 mg/dL 0.7 - 1.3",
        "Urea 28 mg/dL 17 - 43",
        "Sodium 140 mmol/L 136 - 146",
        "Urine Routine Examination",
        "Creatinine 85 mg/dL",
        "Blood Nil",
        "Glucose 50 mg/dL",
        "Complete Blood Count (CBC), Whole Blood EDTA",
        "Haemoglobin 14.1 g/dL 13 - 17",
        "Platelet Count 2.45 Lakhs/cumm 1.5 - 4.1",
    ],
)


# --- health-check packages ------------------------------------------------
def test_a_health_check_is_read_panel_by_panel():
    result = _read(_pdf(*HEALTH_CHECK))
    assert result.classification.status is ClassificationStatus.MULTI_PANEL
    assert set(result.classification.panels) >= {
        ReportType.LIPID_PROFILE, ReportType.LIVER_FUNCTION,
        ReportType.KIDNEY_FUNCTION, ReportType.CBC,
    }
    assert result.report_type is None
    got = _observed(result)
    assert got["cholesterol"] == 182
    assert got["alt"] == 32
    assert got["creatinine"] == 0.9
    assert got["sodium"] == 140
    assert got["hemoglobin"] == 14.1
    assert got["platelets"] == 2.45
    # Each value stands on its own checks; the document as a whole is never
    # "complete", because no schema says what a health check holds.
    assert result.disposition is Disposition.NEEDS_REVIEW
    assert any(i.code == "MULTI_PANEL_REPORT" for i in result.issues)
    assert result.values_forgone == 0


def test_nothing_above_the_first_panel_heading_is_read():
    result = _read(_pdf(*HEALTH_CHECK))
    (above,) = [r for r in result.values if r.value.value == 13.0]
    assert above.value.status is ValueStatus.AMBIGUOUS
    assert above.value.reason == "outside_any_panel"
    assert above.value.analyte is None  # so it cannot clash with the CBC's 14.1


def test_a_two_panel_excerpt_that_names_no_panel_is_still_refused():
    """The discharge summary that set the margin policy prints its results
    under "5. Laboratory Investigations". It names no panel, so it is not a
    health check, and nothing on it is read."""
    pdf = _pdf([
        "5. Laboratory Investigations",
        "Hemoglobin 13.8 g/dL 13.5 - 17.5 g/dL",
        "WBC Count 8,200 /uL 4,000 - 11,000 /uL",
        "Platelet Count 2.3 lakh/uL 1.5 - 4.5 lakh/uL",
        "Total Cholesterol 228 mg/dL < 200 mg/dL",
        "LDL Cholesterol 148 mg/dL < 130 mg/dL",
        "HDL Cholesterol 38 mg/dL > 40 mg/dL",
        "Triglycerides 210 mg/dL < 150 mg/dL",
    ])
    result = _read(pdf)
    assert result.classification.status is ClassificationStatus.REVIEW_REQUIRED
    assert result.values == []


def test_a_narrative_document_is_never_read_as_a_health_check():
    """A discharge summary may print panel headings over results from any day
    of the admission."""
    narrative = ["DISCHARGE SUMMARY", "Date of Admission : 01/03/2026"]
    result = _read(_pdf(narrative + HEALTH_CHECK[0], HEALTH_CHECK[1]))
    assert result.classification.status is ClassificationStatus.REVIEW_REQUIRED
    assert result.values == []


def test_an_empty_result_cell_never_turns_the_range_into_the_result():
    """A laboratory's blank template: the result column is empty, so the
    reference range sits where the result would be."""
    result = _read(_pdf([
        "THYROID PROFILE, FREE, SERUM",
        "TSH, Ultrasensitive 0.550 - 4.780 uIU/mL",
        "Free Thyroxine (T4, Free) 0.89 - 1.76 ng/dL",
        "LIPID PROFILE, BASIC, SERUM",
        "Cholesterol Total mg/dL <200",
        "HDL Cholesterol mg/dL >40",
    ]))
    assert _observed(result) == {}


def test_a_health_check_value_is_held_to_its_own_panel_s_bounds():
    pages = (HEALTH_CHECK[0], [*HEALTH_CHECK[1][:1], "Creatinine 85 mg/dL 0.7 - 1.3",
                               *HEALTH_CHECK[1][2:]])
    result = _read(_pdf(*pages))
    (creatinine,) = [r for r in result.values if r.value.value == 85 and r.value.analyte]
    assert creatinine.value.status is ValueStatus.INVALID


def test_each_value_says_which_page_it_is_on():
    result = _read(_pdf(*HEALTH_CHECK))
    pages = {r.value.analyte: r.provenance.page for r in result.observed_values}
    assert pages["cholesterol"] == 1
    assert pages["creatinine"] == 2
    assert pages["hemoglobin"] == 2


# --- the sample a value was measured in -----------------------------------
def test_a_urine_creatinine_is_never_read_as_a_blood_one():
    result = _read(_pdf(*HEALTH_CHECK))
    (urine,) = [r for r in result.values if r.value.value == 85]
    assert urine.value.status is ValueStatus.AMBIGUOUS
    assert urine.value.reason == "not_a_blood_sample"
    assert urine.value.analyte is None
    # ... and so it does not knock out the serum creatinine as a "conflict".
    assert _observed(result)["creatinine"] == 0.9


def test_a_urine_row_named_blood_does_not_end_the_urine_section():
    """A urine routine prints "Blood  Nil" as one of its own rows."""
    result = _read(_pdf(*HEALTH_CHECK))
    (glucose,) = _by_label(result, "Glucose")
    assert glucose.value.reason == "not_a_blood_sample"


def test_a_blood_panel_heading_after_the_urine_section_ends_it():
    result = _read(_pdf(*HEALTH_CHECK))
    assert _observed(result)["hemoglobin"] == 14.1


def test_the_sample_rule_holds_on_a_single_panel_report_too():
    cbc = [
        "COMPLETE BLOOD COUNT (CBC)",
        "Haemoglobin 13.2 g/dL 13 - 17",
        "Total Leucocyte Count 7800 /cumm 4000 - 11000",
        "Platelet Count 2.45 Lakhs/cumm 1.5 - 4.1",
        "MCV 86.8 fL 83 - 101",
        "Packed Cell Volume 40.1 % 40 - 50",
        "Urine Examination",
        "Glucose 50 mg/dL",
    ]
    result = _read(_pdf(cbc))
    assert result.report_type is ReportType.CBC
    (glucose,) = _by_label(result, "Glucose")
    assert glucose.value.reason == "not_a_blood_sample"
    assert _observed(result)["hemoglobin"] == 13.2


def test_a_urine_report_is_urine_from_its_first_line():
    result = _read(_pdf([
        "URINE ROUTINE EXAMINATION",
        "Specific Gravity 1.020",
        "Pus cells 2 /hpf",
        "Epithelial cells 1 /hpf",
        "Glucose 50 mg/dL",
        "Urine Albumin Creatinine Ratio 25 mg/g < 30",
    ]))
    assert result.report_type is ReportType.URINALYSIS
    (glucose,) = _by_label(result, "Glucose")
    assert glucose.value.reason == "not_a_blood_sample"
    (acr,) = [r for r in result.values if r.value.printed_label.startswith("Urine Albumin")]
    assert acr.value.reason != "not_a_blood_sample"  # a urine analyte belongs here


# --- cumulative reports ---------------------------------------------------
@pytest.mark.parametrize(("printed", "dates"), [
    ("01/Sep/202127/Aug/21 22/Aug/21",
     [date(2021, 9, 1), date(2021, 8, 27), date(2021, 8, 22)]),
    ("16/May/202513/Feb/2525/Oct/24",
     [date(2025, 5, 16), date(2025, 2, 13), date(2024, 10, 25)]),
    ("16/May/2025 30/Mar/24", [date(2025, 5, 16), date(2024, 3, 30)]),
])
def test_dates_printed_run_together_are_split_unambiguously(printed, dates):
    assert parse_dates(printed) == dates


@pytest.mark.parametrize("printed", [
    "1/Feb/20211/Mar/21",        # "2021" + "1/Mar" or "20" + "21/Mar": refuse
    "31/Feb/24",                 # no such date
    "01/Sep/2021 x 27/Aug/21",   # something between the dates
    "01/Sep/3021",               # not a 19xx/20xx year
])
def test_a_date_header_that_is_not_certain_is_refused(printed):
    assert parse_dates(printed) is None


def _cumulative(header: str, *rows: str, collected: str = "01/Sep/2021") -> list:
    text = "\n".join([
        f"Collection Date/Time : {collected} 09:49AM",
        "CBC (Complete Blood Count), Whole Blood EDTA",
        header,
        "09:49AM 10:01AM 02:44PM",
        *rows,
    ])
    return [r for r in extract_raw_values(text) if not r.label.startswith("Collection")]


HEADER = "Date 01/Sep/202127/Aug/21 22/Aug/21 Unit Bio Ref Interval"


def test_a_cumulative_row_is_read_from_the_report_s_own_column():
    (hb,) = _cumulative(HEADER, "Haemoglobin 11.8 11.6 12.0 g/dl 12.0 - 15.0")
    assert hb.value == 11.8
    assert hb.unit == "g/dl"
    assert hb.reference_text == "12.0 - 15.0"
    assert hb.column == "2021-09-01 (column 1 of 3)"


def test_the_column_is_chosen_by_its_date_not_its_position():
    (hb,) = _cumulative(
        "Date 27/Aug/21 01/Sep/2021 Unit Bio Ref Interval",
        "Haemoglobin 11.6 11.8 g/dl 12.0 - 15.0",
    )
    assert hb.value == 11.8
    assert hb.column == "2021-09-01 (column 2 of 2)"


@pytest.mark.parametrize("row", [
    "Platelet Count 186 153 10~9/L 150-410",       # a blank cell: which one?
    "MCV 86.9 86.5 86.3 87.1 fL 83-101",           # one number too many
    "Haemoglobin 11.8 11.6 12.0 - 15.0",           # a blank, and the range's low end fills the gap
])
def test_a_row_that_does_not_fit_the_header_exactly_is_refused(row):
    (raw,) = _cumulative(HEADER, row)
    assert raw.value is None
    assert raw.column == ""


@pytest.mark.parametrize("collected", ["27/Aug/21", "02/Sep/2021"])
def test_no_column_is_read_unless_it_is_the_report_s_collection_date(collected):
    """Older than the newest column, or not in the header at all."""
    (hb,) = _cumulative(HEADER, "Haemoglobin 11.8 11.6 12.0 g/dl 12.0 - 15.0",
                        collected=collected)
    assert hb.value is None


def test_no_column_is_read_when_the_report_prints_no_collection_date():
    text = "\n".join([HEADER, "Haemoglobin 11.8 11.6 12.0 g/dl 12.0 - 15.0"])
    (hb,) = extract_raw_values(text)
    assert hb.value is None


def test_a_cumulative_header_ends_with_its_page():
    raws = _cumulative(
        HEADER,
        "Page 1 of 2",
        "Haemoglobin 11.8 11.6 12.0 g/dl 12.0 - 15.0",
    )
    (hb,) = [r for r in raws if r.label == "Haemoglobin"]
    assert hb.value is None


def test_a_cumulative_report_is_read_end_to_end_with_its_column_recorded():
    result = _read(_pdf([
        "Collection Date/Time : 01/Sep/2021 09:49AM",
        "CBC (Complete Blood Count), Whole Blood EDTA",
        HEADER,
        "Haemoglobin 11.8 11.6 12.0 g/dl 12.0 - 15.0",
        "Total Leucocyte Count 2.8 2.9 27.2 10~9/L 4.0-10.0",
        "Platelet Count 186 153 187 10~9/L 150-410",
        "MCV 86.9 86.5 86.3 fL 83-101",
    ]))
    got = _observed(result)
    assert got == {"hemoglobin": 11.8, "wbc": 2.8, "platelets": 186.0, "mcv": 86.9}
    assert all(r.provenance.column.startswith("2021-09-01") for r in result.observed_values)


# --- scanned PDFs ---------------------------------------------------------
def test_ocr_text_records_where_each_page_begins():
    def token(text, page, y):
        return OcrToken(text=text, page=page, confidence=0.9,
                        bbox=BoundingBox(page=page, x0=0.1, y0=y, x1=0.2, y1=y + 0.01))

    text, starts = _join([token("first", 1, 0.1), token("second", 2, 0.1),
                          token("third", 2, 0.5)])
    assert text == "first\nsecond\nthird"
    assert starts == (0, 6)


def test_a_scanned_pdf_with_no_page_renderer_is_unreadable_not_guessed(blank_pdf, monkeypatch):
    """Holds whether or not pypdfium2 is installed here."""
    monkeypatch.setitem(sys.modules, "pypdfium2", None)  # import now fails
    monkeypatch.setattr(LocalTesseractProvider, "is_available", lambda self: True)
    result = LocalTesseractProvider().run(
        OcrRequest(image_bytes=blank_pdf, media_type=DocumentMediaType.PDF)
    )
    assert result.outcome is OcrOutcome.ENGINE_UNAVAILABLE
    assert "pypdfium2" in result.detail
    assert result.text == ""


def test_a_scanned_pdf_is_rendered_and_read():
    pdfium = pytest.importorskip("pypdfium2")
    if not LocalTesseractProvider().is_available():
        pytest.skip("the Tesseract engine is not installed here")

    text_pdf = _pdf(
        ["LIPID PROFILE", "Total Cholesterol 182 mg/dL 0 - 200"],
        ["COMPLETE BLOOD COUNT", "Haemoglobin 13.2 g/dL 13.0 - 17.0",
         "Platelet Count 245 10^3/uL 150 - 410", "MCV 86.8 fL 83 - 101"],
    )
    document = pdfium.PdfDocument(text_pdf)
    images = [document[i].render(scale=200 / 72).to_pil().convert("L")
              for i in range(len(document))]
    scanned = io.BytesIO()
    images[0].save(scanned, format="PDF", save_all=True, append_images=images[1:])

    result = _read(scanned.getvalue())
    assert result.text_source.value == "OCR"
    assert result.ocr.outcome is OcrOutcome.OK
    hb = next(r for r in result.values if r.value.analyte == "hemoglobin")
    assert hb.value.value == 13.2
    assert hb.provenance.page == 2


def test_classification_of_a_health_check_alone_still_abstains():
    """The classifier itself is unchanged: it abstains, and the multi-panel
    reading is a separate, stricter step after it."""
    text = "\n".join(HEALTH_CHECK[0] + HEALTH_CHECK[1])
    assert classify(text).status is ClassificationStatus.REVIEW_REQUIRED


# ---------------------------------------------------------------- wrapped tables
#
# The same laboratory's plain-extraction shape: the header wraps over a line per
# date and time, and each test's name sits above its numbers with the assay
# method between them. The name-to-number pairing is the dangerous part, so most
# of these tests are about when it must be refused.

WRAPPED_HEADER = [
    "Date 14/Dec/2025", "09:47AM", "01/Jun/25", "07:49AM", "25/Jul/23", "09:34AM",
    "Unit Bio Ref Interval",
]


def _wrapped(*rows: str, header: list[str] = WRAPPED_HEADER, collected: str = "14/Dec/2025") -> dict:
    text = "\n".join([
        f"Collection Date/Time : {collected} 09:47AM",
        "Complete Haemogram, EDTA",
        *header,
        *rows,
    ])
    return {
        r.label: r for r in extract_raw_values(text) if not r.label.startswith("Collection")
    }


def test_a_wrapped_table_reads_the_name_above_its_numbers():
    got = _wrapped(
        "Haemoglobin", "Modified cyanmethemoglobin", "15.1 15.5 14.7 g/dl 13.0 - 17.0",
        "MCV", "Electrical Impedance", "86.5 84.6 85.5 fL 83-101",
    )
    assert got["Haemoglobin"].value == 15.1
    assert got["Haemoglobin"].unit == "g/dl"
    assert got["Haemoglobin"].reference_text == "13.0 - 17.0"
    assert got["Haemoglobin"].column == "2025-12-14 (column 1 of 3)"
    assert got["MCV"].value == 86.5


def test_a_wrapped_value_keeps_its_name_in_the_recorded_source():
    """A reviewer reading the source must see which name the number was paired with."""
    got = _wrapped("Haemoglobin", "Modified cyanmethemoglobin", "15.1 15.5 14.7 g/dl 13.0 - 17.0")
    source = got["Haemoglobin"].line
    assert "Haemoglobin" in source and "15.1 15.5 14.7 g/dl" in source


def test_a_wrapped_table_chooses_its_column_by_date_not_position():
    got = _wrapped(
        "Haemoglobin", "Method", "14.7 15.1 g/dl 13.0 - 17.0",
        header=["Date 25/Jul/23", "09:34AM", "14/Dec/2025", "09:47AM", "Unit Bio Ref Interval"],
    )
    assert got["Haemoglobin"].value == 15.1


def test_a_name_may_wrap_onto_a_second_line():
    got = _wrapped("Glycosylated", "Haemoglobin(Hb A1c)", "HPLC", "7.40 9.80 9.40 % 4.27 - 6.07")
    assert got["Glycosylated Haemoglobin(Hb A1c)"].value == 7.4


def test_a_blank_result_never_lends_its_name_to_the_next_row():
    """Haemoglobin printed nothing. 86.5 belongs to MCV, and is not its value either."""
    with_method = _wrapped(
        "Haemoglobin", "Modified cyanmethemoglobin", "MCV", "Electrical Impedance",
        "86.5 84.6 85.5 fL 83-101",
    )
    assert not any(r.value is not None for r in with_method.values())
    no_method = _wrapped("Haemoglobin", "MCV", "86.5 84.6 85.5 fL 83-101")
    assert not any(r.value is not None for r in no_method.values())


def test_a_name_on_the_second_line_is_not_taken_for_the_row_s_name():
    """Text left over from the last row must not push the real name out of place."""
    got = _wrapped("Calculated", "Haemoglobin", "15.1 15.5 14.7 g/dl 13.0 - 17.0")
    assert not any(r.value is not None for r in got.values())


@pytest.mark.parametrize("row", [
    "15.1 15.5 g/dl 13.0 - 17.0",            # a blank cell: which column is it?
    "15.1 15.5 14.7 13.2 g/dl 13.0 - 17.0",  # one number too many
    "15.1 15.5 13.0 - 17.0",                 # a blank, and the range fills the gap
    "15.1 15.5 14.7 H g/dl 13.0 - 17.0",     # not the printed shape: a flag where the unit goes
    "15.1 15.5 14.7 g/dl is the usual range",  # words where the range goes
])
def test_a_wrapped_row_that_does_not_fit_exactly_is_refused(row):
    got = _wrapped("Haemoglobin", "Method", row)
    assert not any(r.value is not None for r in got.values())


def test_a_sentence_beside_a_test_name_is_not_a_result():
    got = _wrapped(
        "HbA1c", "6.5 % indicates diabetes",
        header=["Date 14/Dec/2025", "09:47AM", "Unit Bio Ref Interval"],
    )
    assert not any(r.value is not None for r in got.values())


def test_a_wrapped_table_with_one_date_reads_that_date():
    got = _wrapped(
        "Creatinine", "Alkaline picrate kinetic", "0.79 mg/dL 0.9 - 1.3",
        header=["Date 14/Dec/2025", "09:47AM", "Unit Bio Ref", "Interval"],
    )
    assert got["Creatinine"].value == 0.79
    assert got["Creatinine"].column == "2025-12-14 (column 1 of 1)"


def test_a_range_with_no_result_in_a_one_date_table_is_not_a_result():
    got = _wrapped(
        "Creatinine", "Method", "0.9 - 1.3 mg/dL",
        header=["Date 14/Dec/2025", "09:47AM", "Unit Bio Ref Interval"],
    )
    assert not any(r.value is not None for r in got.values())


@pytest.mark.parametrize("collected", ["01/Jun/25", "15/Dec/2025"])
def test_a_wrapped_table_is_not_read_unless_its_newest_date_is_the_collection_date(collected):
    got = _wrapped(
        "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0", collected=collected,
    )
    assert not any(r.value is not None for r in got.values())


def test_a_wrapped_table_printing_one_date_twice_is_refused():
    got = _wrapped(
        "Haemoglobin", "Method", "15.1 15.5 g/dl 13.0 - 17.0",
        header=["Date 14/Dec/2025", "09:47AM", "14/Dec/2025", "06:00AM", "Unit Bio Ref Interval"],
    )
    assert not any(r.value is not None for r in got.values())


def test_a_wrapped_header_that_never_reaches_its_column_titles_is_refused():
    got = _wrapped(
        "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0",
        header=["Date 14/Dec/2025", "09:47AM", "01/Jun/25", "07:49AM", "25/Jul/23", "09:34AM"],
    )
    assert not any(r.value is not None for r in got.values())


def test_a_short_capitalised_test_name_does_not_close_the_table():
    got = _wrapped(
        "MCHC", "Calculated", "33.3 32.7 32.0 g/dl 31.5-34.5",
        "Platelet Count", "Electrical Impedance", "161 220 171 10~9/L 150-410",
    )
    assert got["MCHC"].value == 33.3
    assert got["Platelet Count"].value == 161


def test_a_capitalised_heading_closes_the_table():
    got = _wrapped("OTHER SECTION", "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0")
    assert not any(r.value is not None for r in got.values())


def test_a_wrapped_table_ends_with_its_page():
    got = _wrapped("Page 1 of 2", "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0")
    assert not any(r.value is not None for r in got.values())


def test_a_name_above_its_numbers_is_never_read_outside_a_wrapped_table():
    text = "\n".join([
        "Collection Date/Time : 14/Dec/2025 09:47AM",
        "Haemoglobin", "Method", "15.1 g/dl 13.0 - 17.0",
    ])
    assert not any(
        r.value is not None for r in extract_raw_values(text)
        if not r.label.startswith("Collection")
    )


def test_a_wrapped_report_is_read_end_to_end():
    result = _read(_pdf([
        "Collection Date/Time : 14/Dec/2025 09:47AM",
        "Complete Haemogram, Peripheral Smear and ESR, EDTA",
        *WRAPPED_HEADER,
        "Haemoglobin", "Modified cyanmethemoglobin", "15.1 15.5 14.7 g/dl 13.0 - 17.0",
        "Total Leucocyte Count (TLC)", "Electrical Impedance", "5.7 8.3 9.4 10~9/L 4.0-10.0",
        "Platelet Count", "Electrical Impedance", "161 220 171 10~9/L 150-410",
        "MCV", "Electrical Impedance", "86.5 84.6 85.5 fL 83-101",
    ]))
    assert _observed(result) == {"hemoglobin": 15.1, "wbc": 5.7, "platelets": 161.0, "mcv": 86.5}
    assert all(r.provenance.column.startswith("2025-12-14") for r in result.observed_values)


def test_the_ifcc_hba1c_is_never_read_as_the_percentage():
    """The same test in mmol/mol. 57 as a percentage would be an impossible HbA1c."""
    assert canonical_analyte("Glycosylated Haemoglobin(Hb A1c)") == "hba1c"
    assert canonical_analyte("Glycosylated Haemoglobin(Hb A1c) IFCC") is None


def test_a_capitalised_method_under_a_name_does_not_close_the_table():
    got = _wrapped(
        "Thyroid Stimulating Hormone", "CLIA", "6.78 6.74 5.06 µIU/mL 0.38 - 5.33",
        "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0",
    )
    assert got["Thyroid Stimulating Hormone"].value == 6.78
    assert got["Haemoglobin"].value == 15.1


def test_a_method_word_with_no_name_above_it_closes_the_table():
    got = _wrapped("CLIA", "Haemoglobin", "Method", "15.1 15.5 14.7 g/dl 13.0 - 17.0")
    assert not any(r.value is not None for r in got.values())
