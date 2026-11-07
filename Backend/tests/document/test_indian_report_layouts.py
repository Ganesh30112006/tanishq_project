"""Reports laid out the way Indian laboratory software prints them.

Found by failure discovery on 2026-11-02: a results table prints one text run
per cell, and the default PDF text extraction put every cell on its own line,
so "Haemoglobin", "13.2" and "g/dL" arrived three lines apart and NO value was
read from any table-laid-out report. These pin the fix, the units and names
those reports use, and - because reading by position joins text that used to
stay apart - that no layout makes a wrong value come out as one the reader
stands behind.

Documents are built here, in memory. Nothing in this file is a label.
"""
from __future__ import annotations

import io

import pytest

from intelligence.document.contracts import ValueStatus
from intelligence.document.extraction.analytes import extract_raw_values
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.normalization.units import normalize_value
from intelligence.document.pipeline import process_document

COLS = (30, 230, 300, 390)  # test, result, unit, reference


def _table_pdf(title: str, rows, *, cols=COLS, extra=None) -> bytes:
    """One text run per cell, as lab software prints a table."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(595, 842))
    c.setFont("Helvetica", 9)
    c.drawString(30, 810, title)
    y = 790
    for row in rows:
        for x, cell in zip(cols, row, strict=True):
            if cell:
                c.drawString(x, y, cell)
        y -= 14
    if extra:
        extra(c)
    c.showPage()
    c.save()
    return buffer.getvalue()


def _observed(result) -> dict[str, float]:
    return {
        r.value.analyte: r.value.normalized.value
        for r in result.values
        if r.value.status is ValueStatus.OBSERVED
    }


# --- the table itself ------------------------------------------------------
def test_a_table_laid_out_report_is_read_row_by_row():
    pdf = _table_pdf("COMPLETE BLOOD COUNT (CBC)", [
        ("Haemoglobin", "13.2", "g/dL", "13.0 - 17.0"),
        ("Total Leucocyte Count", "7,800", "/cumm", "4000 - 11000"),
        ("Platelet Count", "2.45", "Lakhs/cumm", "1.5 - 4.1"),
        ("MCV", "86.8", "fL", "83 - 101"),
    ])
    got = _observed(process_document(pdf, declared_type="application/pdf"))
    assert got["hemoglobin"] == pytest.approx(132.0)
    assert got["wbc"] == pytest.approx(7.8)
    assert got["platelets"] == pytest.approx(245.0)
    assert got["mcv"] == pytest.approx(86.8)


def test_each_value_keeps_the_row_it_came_from():
    pdf = _table_pdf("LIVER FUNCTION TEST (LFT)", [
        ("SGOT (AST)", "28", "U/L", "5 - 40"),
        ("SGPT (ALT)", "35", "U/L", "5 - 41"),
    ])
    result = process_document(pdf, declared_type="application/pdf")
    by_analyte = {r.value.analyte: r.provenance.source_text for r in result.values}
    assert by_analyte["ast"].startswith("SGOT (AST)") and "28" in by_analyte["ast"]
    assert by_analyte["alt"].startswith("SGPT (ALT)") and "35" in by_analyte["alt"]


# --- layouts that join text that used to stay apart -------------------------
def test_two_tables_side_by_side_never_yield_a_wrong_value():
    def right_table(c):
        for i, row in enumerate([("MCV", "86.8", "fL", "83 - 101"), ("PCV", "40.1", "%", "40 - 50")]):
            for x, cell in zip((320, 420, 455, 500), row, strict=True):
                c.drawString(x, 790 - 14 * i, cell)

    pdf = _table_pdf(
        "COMPLETE BLOOD COUNT (CBC)",
        [("Haemoglobin", "13.2", "g/dL", "13 - 17"), ("Platelet Count", "245", "10^3/uL", "150 - 410")],
        cols=(30, 140, 175, 220), extra=right_table,
    )
    truth = {"hemoglobin": 132.0, "platelets": 245.0, "mcv": 86.8, "hematocrit": 40.1}
    for analyte, value in _observed(process_document(pdf, declared_type="application/pdf")).items():
        assert value == pytest.approx(truth[analyte]), analyte


def test_a_wrapped_test_name_cannot_pass_one_result_off_as_another():
    """"Mean Corpuscular / Haemoglobin 28.6 pg" reads as haemoglobin 28.6. The
    unit is what stops it: pg is not a haemoglobin unit."""
    def wrapped(c):
        c.drawString(30, 776, "Mean Corpuscular")

    pdf = _table_pdf("COMPLETE BLOOD COUNT (CBC)", [], extra=lambda c: (
        wrapped(c), c.drawString(30, 762, "Haemoglobin"),
        c.drawString(230, 762, "28.6"), c.drawString(300, 762, "pg"), c.drawString(390, 762, "27 - 32"),
    ))
    assert "hemoglobin" not in _observed(process_document(pdf, declared_type="application/pdf"))


# --- units Indian reports print ----------------------------------------------
@pytest.mark.parametrize(("analyte", "value", "unit", "expected"), [
    ("wbc", 7800, "/cumm", 7.8),
    ("wbc", 7800, "cells/cmm", 7.8),
    ("platelets", 245000, "/cumm", 245.0),
    ("platelets", 2.45, "Lakhs/cumm", 245.0),
    ("platelets", 2.45, "lakh/µL", 245.0),
    ("platelets", 245, "10^3/µL", 245.0),     # micro sign
    ("platelets", 245, "10^3/μL", 245.0),     # Greek mu
    ("rbc", 4.62, "mill/cumm", 4.62),
    ("rbc", 4.1, "10^6/µL", 4.1),
    ("hemoglobin", 10.2, "gm/dl", 102.0),
])
def test_indian_count_units_convert_exactly(analyte, value, unit, expected):
    result = normalize_value(analyte, value, unit)
    assert result.convertible, unit
    assert result.value == pytest.approx(expected)


def test_lakhs_are_never_applied_to_a_count_not_printed_in_lakhs():
    assert not normalize_value("wbc", 2.3, "lakhs/cumm").convertible
    assert not normalize_value("rbc", 2.3, "lakhs/cumm").convertible


# --- names Indian reports print ----------------------------------------------
@pytest.mark.parametrize(("label", "analyte"), [
    ("Hemoglobin (Hb)", "hemoglobin"),
    ("LDL Cholesterol (Calculated)", "ldl"),
    ("LDL Cholesterol (Direct)", "ldl"),
    ("Glucose Fasting (FBS)", "fasting_glucose"),
    ("Glucose (Fasting)", "fasting_glucose"),
    ("Glucose Post Prandial (PPBS)", "random_glucose"),
])
def test_indian_spellings_resolve(label, analyte):
    assert canonical_analyte(label) == analyte


@pytest.mark.parametrize("label", [
    "Calcium (Ionised)", "Ionised Calcium", "RDW-SD", "VLDL Cholesterol", "T3 Total",
])
def test_brackets_and_lookalikes_are_not_stripped_into_another_analyte(label):
    """The new spellings are listed one by one. A general bracket-stripping
    rule would turn an ionised calcium into a total calcium."""
    assert canonical_analyte(label) is None


# --- flag between value and unit ---------------------------------------------
def test_a_unit_printed_after_the_flag_is_kept():
    (raw,) = extract_raw_values("Hemoglobin (Hb)   10.2 L   gm/dl   13 - 17")
    assert raw.value == 10.2
    assert raw.printed_flag == "L"
    assert raw.unit == "gm/dl"
    assert raw.reference_text == "13 - 17"


# --- found on laboratory sample reports downloaded on 2026-11-02 --------------
#
# Fourteen sample reports that Indian laboratories publish on their own sites
# were run through the reader. These pin what they showed. The reports
# themselves are not kept, and nothing here is a label.

def test_a_report_drawn_inside_a_form_object_is_still_read():
    """HTML-to-PDF generators draw the whole page inside a form XObject.
    Layout extraction ignores that text without raising, so four of the
    downloaded reports came out empty - and one, with only a watermark outside
    the form, came out as the watermark. The plain text is used when layout
    loses any of it."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(595, 842))
    c.setFont("Helvetica", 9)
    c.drawString(30, 820, "SAMPLE REPORT")  # outside the form, as a watermark is
    c.beginForm("page")
    c.drawString(30, 810, "COMPLETE BLOOD COUNT (CBC)")
    c.drawString(30, 790, "Haemoglobin (Hb) 11.0 gm/dL 12.5 - 16.0")
    c.drawString(30, 776, "Total Leucocytes (WBC) count 8200 cells/cu.mm 4000 - 10500")
    c.endForm()
    c.doForm("page")
    c.showPage()
    c.save()

    got = _observed(process_document(buffer.getvalue(), declared_type="application/pdf"))
    assert got["hemoglobin"] == pytest.approx(110.0)
    assert got["wbc"] == pytest.approx(8.2)


@pytest.mark.parametrize(("analyte", "value", "unit", "expected"), [
    ("wbc", 8200, "cells/cu.mm", 8.2),
    ("wbc", 8200, "/c.mm", 8.2),
    ("rbc", 3.95, "mill/cu.mm", 3.95),
    ("platelets", 2.45, "lakhs/cu.mm", 245.0),
])
def test_the_cubic_millimetre_printed_with_a_dot_converts_exactly(analyte, value, unit, expected):
    result = normalize_value(analyte, value, unit)
    assert result.convertible, unit
    assert result.value == pytest.approx(expected)


def test_a_per_cubic_millimetre_unit_with_a_dot_is_taken_as_the_unit():
    (raw,) = extract_raw_values("Total Leucocyte Count 8200 /c.mm 4000 - 10500")
    assert raw.unit == "/c.mm"
    assert raw.reference_text == "4000 - 10500"


@pytest.mark.parametrize(("label", "analyte"), [
    ("Erythrocyte (RBC) Count", "rbc"),
    ("Total Leucocytes (WBC) count", "wbc"),
    ("PCV (Packed Cell Volume)", "hematocrit"),
    ("MCV (Mean Corpuscular Volume)", "mcv"),
    ("MCH (Mean Corpuscular Hb)", "mch"),
    ("MCHC (Mean Corpuscular Hb Concn.)", "mchc"),
    ("Free Triiodothyronine (FT3)", "free_t3"),
    ("Free Thyroxine (FT4)", "free_t4"),
])
def test_names_printed_with_their_abbreviation_resolve(label, analyte):
    assert canonical_analyte(label) == analyte


@pytest.mark.parametrize("label", [
    "Absolute Neutrophil Count", "Absolute Neutrophils Count", "ANC",
    "Absolute Lymphocyte Count", "Absolute Monocyte Count",
    "Absolute Eosinophil Count", "AEC", "Absolute Basophil Count",
])
def test_an_absolute_count_is_not_given_the_percentage_s_name(label):
    assert canonical_analyte(label) is None


def test_a_percentage_printed_beside_its_absolute_count_is_still_read():
    """Most Indian CBCs print both. When the absolute count took the
    percentage's name, the pair looked like one test with two values and the
    correctly read percentage was held as a conflict."""
    pdf = _table_pdf("COMPLETE BLOOD COUNT (CBC)", [
        ("Absolute Lymphocyte Count", "2050", "/c.mm", "1000 - 3000"),
        ("Absolute Eosinophil Count", "82", "/c.mm", "20 - 500"),
        ("Lymphocytes", "25", "%", "20 - 40"),
        ("Eosinophils", "1", "%", "1 - 6"),
    ])
    result = process_document(pdf, declared_type="application/pdf")
    got = _observed(result)
    assert got["lymphocytes"] == pytest.approx(25.0)
    assert got["eosinophils"] == pytest.approx(1.0)
    assert not any(r.value.status is ValueStatus.CONFLICTING for r in result.values)
