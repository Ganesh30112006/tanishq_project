from __future__ import annotations

from decimal import Decimal

from apps.reports.extraction import extract_text

CBC_TEXT = """\
COMPLETE BLOOD COUNT
Hemoglobin: 13.5 g/dL
WBC : 6.2 10^9/L
Platelet count   250 10^9/L
Random comment line that is not a test
"""


def test_extracts_known_analytes_with_values_and_units():
    out = extract_text(CBC_TEXT)
    by = out.by_analyte()
    assert set(by) == {"hemoglobin", "wbc", "platelets"}
    hb = by["hemoglobin"][0]
    assert hb.value_number == Decimal("13.5")
    assert hb.unit == "g/dL"
    assert hb.parsed


def test_unmatched_lines_are_not_guessed():
    out = extract_text(CBC_TEXT)
    assert any("Random comment" in line for line in out.unmatched_lines)
    # Nothing invented for the comment line.
    assert all(v.analyte in {"hemoglobin", "wbc", "platelets"} for v in out.values)


def test_value_without_parseable_number_is_low_confidence_and_unparsed():
    out = extract_text("Glucose: pending")
    assert out.values == [] or not out.values[0].parsed
