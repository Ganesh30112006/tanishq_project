"""Near-miss report lines, and what the parser is allowed to conclude.

This is **not** the clinical gold-standard benchmark and must never be
confused with it. Nothing here is clinician-annotated and nothing here says
whether a value is clinically meaningful. Every case answers one question:

    can the parser be made to manufacture a structured clinical fact out of
    text that does not support one?

The cases are written from the shapes real reports and real OCR actually
produce - the same test name spelled six ways, two quantities that share a
printed name, a number OCR split in half, a result the assay declined to
measure. Each declares the analyte it must resolve to (or ``None``), and the
statuses it is allowed to end in.

The bug that started this file: ``HbA1c 6.2 %`` once parsed as the analyte
"HbA" with the value 1 and the unit "c". It was found by exercising the
implementation, not by reading the rules, and it had been live for three
commits.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.document.contracts import ValueStatus

#: Statuses that mean "no clinical value was persisted from this line".
NOT_A_FACT = frozenset({
    ValueStatus.AMBIGUOUS, ValueStatus.INVALID,
    ValueStatus.UNREADABLE, ValueStatus.CONFLICTING,
})


@dataclass(frozen=True, slots=True)
class Case:
    """One line of report text and the verdict the parser must reach."""

    line: str
    #: The canonical analyte this must resolve to, or None if it must not
    #: resolve to any analyte at all.
    analyte: str | None
    #: The statuses this line may end in. More than one where the surrounding
    #: schema legitimately changes the answer.
    allowed: frozenset[ValueStatus]
    #: The normalised value, when the line is supposed to yield one.
    normalised: float | None = None
    why: str = ""

    @property
    def must_not_persist(self) -> bool:
        return not (self.allowed & {ValueStatus.OBSERVED, ValueStatus.NEEDS_REVIEW})


def _ok(line, analyte, normalised, why=""):
    return Case(line, analyte, frozenset({ValueStatus.OBSERVED}), normalised, why)


def _ambiguous(line, analyte=None, why=""):
    return Case(line, analyte, frozenset({ValueStatus.AMBIGUOUS}), None, why)


# --- the same test, spelled the way six laboratories spell it -------
SPELLING = [
    _ok("HbA1c 6.2 % 4.0 - 5.6", "hba1c", 44.26245,
        "the original bug: read as analyte 'HbA', value 1, unit 'c'"),
    _ok("HBA1C 6.2 % 4.0 - 5.6", "hba1c", 44.26245),
    _ok("HbA1c: 6.2 % 4.0 - 5.6", "hba1c", 44.26245),
    _ok("HbA1c 6.2% 4.0 - 5.6", "hba1c", 44.26245, "no space before the unit"),
    _ok("HbA1c ........ 6.2 % 4.0 - 5.6", "hba1c", 44.26245,
        "dot leaders, common in printed tables"),
    _ok("Hb A1c 6.2 % 4.0 - 5.6", "hba1c", 44.26245,
        "OCR frequently inserts a space inside the name"),
    _ok("Glycated Hb (HbA1c) 6.2 % 4.0 - 5.6", "hba1c", 44.26245),
    _ok("Glycosylated Hemoglobin 6.2 % 4.0 - 5.6", "hba1c", 44.26245),
]

# --- names that look alike and are not the same measurement ---------
LOOKALIKES = [
    _ok("Total Calcium 9.2 mg/dL 8.6 - 10.2", "calcium", 2.2954),
    _ok("Calcium 9.2 mg/dL 8.6 - 10.2", "calcium", 2.2954),
    _ambiguous("Ionized Calcium 4.6 mg/dL 4.5 - 5.3", None,
               "a much narrower interval; reading it as total calcium calls a "
               "normal result low"),
    _ambiguous("Calcium (Ionised) 1.18 mmol/L 1.15 - 1.33", None),
    _ambiguous("Free Calcium 1.18 mmol/L", None),

    _ok("Urea 38 mg/dL 15 - 40", "urea", 6.327),
    _ok("Blood Urea 38 mg/dL 15 - 40", "urea", 6.327),
    _ok("BUN 18 mg/dL 7 - 20", "bun", 6.426),
    _ok("Blood Urea Nitrogen 18 mg/dL 7 - 20", "bun", 6.426),
    _ok("Urea Nitrogen 18 mg/dL 7 - 20", "bun", 6.426),

    _ok("Fasting Glucose 126 mg/dL 70 - 99", "fasting_glucose", 6.993),
    _ok("FBS 126 mg/dL 70 - 99", "fasting_glucose", 6.993),
    _ok("Random Blood Sugar 180 mg/dL", "random_glucose", 9.99),
    _ok("Post Prandial Blood Sugar 180 mg/dL", "random_glucose", 9.99),
    _ok("Plasma Glucose 126 mg/dL", "glucose", 6.993),

    _ok("RDW-CV 14.1 % 11.5 - 14.5", "rdw", 14.1),
    _ambiguous("RDW-SD 46.2 fL 39 - 46", None,
               "a width in femtolitres, not the CV percentage"),

    _ok("eGFR 55 mL/min/1.73m2", "egfr", 55.0),
    _ambiguous("Creatinine Clearance 55 mL/min", None,
               "not normalised to body surface area"),
]

# --- a percentage is not an absolute count --------------------------
DIFFERENTIAL = [
    _ok("Eosinophils 4.2 % 1 - 6", "eosinophils", 4.2),
    Case("Absolute Eosinophil Count 0.45 10^9/L 0.02 - 0.5", "eosinophils",
         frozenset({ValueStatus.AMBIGUOUS}), None,
         "no conversion rule exists for an absolute count on purpose"),
    Case("AEC 450 /uL 40 - 440", "eosinophils",
         frozenset({ValueStatus.AMBIGUOUS}), None),
    Case("Absolute Neutrophil Count 4.1 10^9/L", "neutrophils",
         frozenset({ValueStatus.AMBIGUOUS}), None),
    _ok("Neutrophils 58 % 40 - 75", "neutrophils", 58.0),
]

# --- what OCR does to numbers ---------------------------------------
OCR_DAMAGE = [
    Case("Hemoglobin 1 3.4 g/dL 13.0 - 17.0", "hemoglobin",
         frozenset({ValueStatus.AMBIGUOUS}), None,
         "OCR split 13.4; taking the 1 reports a haemoglobin of 1 g/dL"),
    Case("Creatinine 1.2 / 1.4 mg/dL 0.6 - 1.2", "creatinine",
         frozenset({ValueStatus.AMBIGUOUS}), None,
         "two results on one line; neither may be chosen"),
    _ambiguous("Hemoglobin l3.4 g/dL 13.0 - 17.0", None,
               "OCR read the leading 1 as a lowercase L"),
    Case("Hemoglobin 13.4", "hemoglobin",
         frozenset({ValueStatus.AMBIGUOUS}), None, "no unit at all"),
    Case("Hemoglobin 13.4 parsecs 13.0 - 17.0", "hemoglobin",
         frozenset({ValueStatus.AMBIGUOUS}), None, "a unit no rule knows"),
]

# --- results the assay declined to measure --------------------------
CENSORED = [
    Case("TSH <0.01 uIU/mL 0.4 - 4.0", "tsh",
         frozenset({ValueStatus.AMBIGUOUS}), None,
         "a suppressed TSH is clinically important and is not the number 0.01"),
    Case("TSH >100 uIU/mL 0.4 - 4.0", "tsh",
         frozenset({ValueStatus.AMBIGUOUS}), None),
    Case("Troponin < 0.01 ng/mL", None,
         frozenset({ValueStatus.AMBIGUOUS}), None),
]

# --- lines that are not results at all ------------------------------
NOT_RESULTS = [
    "Page 1 of 3",
    "Patient Age 45 Years",
    "Sample collected on 12/03/2026 at 09:15",
    "Reference Range 13.0 - 17.0",
    "Lab No 2026/00417",
    "Reported by Dr A Kumar, MD (Path)",
    "Method: HPLC",
    "UHID 88213",
    "Investigation Result Unit Reference",
]

ALL_CASES = SPELLING + LOOKALIKES + DIFFERENTIAL + OCR_DAMAGE + CENSORED
