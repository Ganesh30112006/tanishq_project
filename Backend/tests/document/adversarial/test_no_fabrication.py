"""The parser may not manufacture a clinical fact out of text that has none.

One invariant, checked from several directions: a line that does not clearly
carry an analyte, a value and a unit must not end in a status that persists a
clinical value. Being unable to read a report is safe. Reading it wrongly with
confidence is the failure this whole module exists to prevent, and it is
invisible downstream - a haemoglobin of 1 g/dL looks exactly like a
haemoglobin of 13.4 g/dL once it is a number in a field.

These are invariants, not accuracy measurements. Nothing here is
clinician-annotated, and passing it says nothing about whether the system
reads reports *well* - only that it does not read them wrongly and quietly.
That question is the clinical gold-standard benchmark's, and it is separate on
purpose.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import ValueStatus
from intelligence.document.extraction import extract_raw_values
from intelligence.document.normalization import canonical_analyte
from intelligence.document.validation import validate_value
from tests.document.adversarial.corpus import (
    ALL_CASES,
    CENSORED,
    DIFFERENTIAL,
    LOOKALIKES,
    NOT_A_FACT,
    NOT_RESULTS,
    OCR_DAMAGE,
    SPELLING,
)


def _validate(line: str, schema=None):
    raws = extract_raw_values(line + "\n")
    if not raws:
        return None
    return validate_value(raws[0], schema=schema)


def _ids(cases):
    return [c.line for c in cases]


# --- the one invariant, over every case -----------------------------
@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_the_verdict_is_the_one_the_case_allows(case):
    result = _validate(case.line)
    assert result is not None, (
        f"{case.line!r} produced no extraction at all. Silence is safe but it "
        f"is not the recorded expectation; update the case if this is right."
    )
    assert result.status in case.allowed, (
        f"{case.line!r} -> {result.status.value} "
        f"(reason {result.reason!r}, issues {result.issues}). {case.why}"
    )
    assert result.analyte == case.analyte, (
        f"{case.line!r} resolved to {result.analyte!r}, expected "
        f"{case.analyte!r}. {case.why}"
    )


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_a_line_that_is_not_a_fact_never_persists_one(case):
    result = _validate(case.line)
    if not case.must_not_persist:
        return
    assert not result.persists_clinical_value
    assert result.status in NOT_A_FACT
    # And it says which kind of "no" it is, so a person is not left guessing.
    assert result.reason, f"{case.line!r} refused without saying why"


@pytest.mark.parametrize("case", ALL_CASES, ids=_ids(ALL_CASES))
def test_a_line_that_is_a_fact_normalises_to_the_expected_number(case):
    if case.normalised is None:
        return
    result = _validate(case.line)
    assert result.normalized is not None and result.normalized.convertible
    assert result.normalized.value == pytest.approx(case.normalised)


# --- the same test, spelled six ways --------------------------------
@pytest.mark.parametrize("case", SPELLING, ids=_ids(SPELLING))
def test_every_spelling_of_hba1c_reaches_the_same_value(case):
    """The original bug, pinned from every direction it can be written."""
    result = _validate(case.line)
    assert result.analyte == "hba1c"
    assert result.value == 6.2
    assert result.unit == "%"
    assert result.status is ValueStatus.OBSERVED


# --- names that look alike --------------------------------------------
@pytest.mark.parametrize("case", LOOKALIKES, ids=_ids(LOOKALIKES))
def test_a_lookalike_never_borrows_the_other_ones_identity(case):
    result = _validate(case.line)
    assert result.analyte == case.analyte, case.why


def test_the_refused_lookalikes_are_refused_at_the_alias_table():
    """Not by luck further down the pipeline."""
    for label in ("Ionized Calcium", "Free Calcium", "RDW-SD",
                  "Creatinine Clearance"):
        assert canonical_analyte(label) is None, label


def test_urea_and_bun_do_not_collapse_into_one_number():
    urea = _validate("Urea 38 mg/dL 15 - 40")
    bun = _validate("BUN 38 mg/dL 7 - 20")
    assert urea.analyte != bun.analyte
    assert urea.normalized.value != bun.normalized.value


# --- percentages and absolute counts ---------------------------------
@pytest.mark.parametrize("case", DIFFERENTIAL, ids=_ids(DIFFERENTIAL))
def test_an_absolute_count_is_never_read_against_a_percentage_interval(case):
    result = _validate(case.line)
    assert result.status in case.allowed
    if case.must_not_persist:
        assert result.reason == "unit_not_convertible_for_analyte"


# --- what OCR does to numbers ----------------------------------------
@pytest.mark.parametrize("case", OCR_DAMAGE, ids=_ids(OCR_DAMAGE))
def test_damaged_numbers_produce_no_number(case):
    result = _validate(case.line)
    assert result.value is None or not result.persists_clinical_value


def test_a_split_number_does_not_report_its_first_half():
    """The shape that turns a haemoglobin of 13.4 into one of 1."""
    result = _validate("Hemoglobin 1 3.4 g/dL 13.0 - 17.0")
    assert result.value is None
    assert result.reason == "more_than_one_number_on_the_line"
    assert result.status is ValueStatus.AMBIGUOUS


def test_two_results_on_one_line_pick_neither():
    result = _validate("Creatinine 1.2 / 1.4 mg/dL 0.6 - 1.2")
    assert result.value is None
    assert result.reason == "more_than_one_number_on_the_line"


# --- results the assay declined to measure ----------------------------
@pytest.mark.parametrize("case", CENSORED, ids=_ids(CENSORED))
def test_a_censored_result_is_kept_but_never_becomes_a_number(case):
    """Dropping the line loses a real finding; reading "<0.01" as 0.01 invents
    a precision the assay explicitly declined to give."""
    result = _validate(case.line)
    assert result is not None, "the line must not be silently discarded"
    assert result.value is None
    assert result.reason == "result_is_a_bound_not_a_number"
    assert not result.persists_clinical_value


def test_the_censored_text_is_preserved_verbatim():
    raw = extract_raw_values("TSH <0.01 uIU/mL 0.4 - 4.0\n")[0]
    assert raw.value_text == "<0.01"
    assert raw.unit == "uIU/mL"
    assert raw.reference_text == "0.4 - 4.0"


# --- lines that are not results at all --------------------------------
@pytest.mark.parametrize("line", NOT_RESULTS)
def test_report_furniture_never_becomes_a_result(line):
    result = _validate(line)
    if result is None:
        return
    assert result.analyte is None, (
        f"{line!r} resolved to the analyte {result.analyte!r}"
    )
    assert not result.persists_clinical_value


# --- the guarantee, stated once ---------------------------------------
def test_exactly_one_status_persists_a_clinical_value():
    persisting = [s for s in ValueStatus if s.persists_clinical_value]
    assert persisting == [ValueStatus.OBSERVED]


def test_not_found_is_never_the_status_of_an_extracted_value():
    """It is the answer to a lookup. A value that was not found was not
    extracted, so no extraction may carry it."""
    for case in ALL_CASES:
        result = _validate(case.line)
        if result is not None:
            assert result.status is not ValueStatus.NOT_FOUND, case.line
