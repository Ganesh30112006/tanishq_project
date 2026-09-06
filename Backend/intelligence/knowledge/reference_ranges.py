"""Fallback reference intervals, used only when the report printed none.

**The laboratory's own printed range wins, always.** It was set by the lab that
ran the assay, on its instrument, for its population; ours is a textbook
average. This table exists so that a report which omits the range can still be
read, and every finding that relies on it says so.

Two kinds of number live here and they are not interchangeable:

``reference_interval``
    The central range of a healthy population. Outside it means "unusual",
    which is a laboratory statement.

``decision_threshold``
    A number a guideline chose because acting above it changes outcomes -
    LDL cholesterol, HbA1c. Outside it means "worth acting on", which is a
    clinical statement, and it is *not* the same as abnormal.

Blurring the two is how a system ends up telling a patient their cholesterol is
"abnormal" when it is merely above a treatment target. Findings built on a
``decision_threshold`` carry that caveat into their output.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Bump when a bound changes; findings record which version they used.
RANGE_TABLE_VERSION = "adult-ranges-1"


@dataclass(frozen=True, slots=True)
class Interval:
    analyte: str
    unit: str
    low: float | None
    high: float | None
    #: "reference_interval" | "decision_threshold"
    kind: str
    #: "any" | "male" | "female"
    applies_to: str = "any"
    source: str = ""
    note: str = ""

    def describe(self) -> str:
        if self.low is not None and self.high is not None:
            return f"{self.low} - {self.high} {self.unit}"
        if self.high is not None:
            return f"< {self.high} {self.unit}"
        if self.low is not None:
            return f"> {self.low} {self.unit}"
        return ""


_TABLE: tuple[Interval, ...] = (
    # --- haematology, in canonical units ---------------------------
    Interval("hemoglobin", "g/L", 130.0, 175.0, "reference_interval", "male",
             source="WHO/common adult laboratory intervals"),
    Interval("hemoglobin", "g/L", 120.0, 155.0, "reference_interval", "female",
             source="WHO/common adult laboratory intervals"),
    Interval("hemoglobin", "g/L", 120.0, 175.0, "reference_interval", "any",
             source="WHO/common adult laboratory intervals",
             note="sex not known, so the wider of the two intervals is used and "
                  "a borderline result may be missed"),
    Interval("wbc", "10^9/L", 4.0, 11.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("platelets", "10^9/L", 150.0, 450.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("mcv", "fL", 80.0, 100.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("eosinophils", "%", 1.0, 6.0, "reference_interval", "any",
             source="common adult differential-count interval",
             note="this is a PERCENTAGE of white cells, not an absolute count. "
                  "A raised percentage with a normal total white count is not "
                  "eosinophilia, and a percentage alone cannot settle that. No "
                  "fallback interval is given for an absolute eosinophil count, "
                  "so one is left uncompared rather than checked against the "
                  "wrong scale"),
    Interval("ferritin", "ng/mL", 30.0, 400.0, "reference_interval", "male",
             source="common adult laboratory intervals"),
    Interval("ferritin", "ng/mL", 15.0, 200.0, "reference_interval", "female",
             source="common adult laboratory intervals"),
    Interval("ferritin", "ng/mL", 15.0, 400.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="sex not known; the wider interval is used"),

    # --- glycaemia -------------------------------------------------
    Interval("glucose", "mmol/L", 3.9, 5.5, "reference_interval", "any",
             source="fasting plasma glucose, common laboratory interval",
             note="assumes a FASTING sample; a random or post-meal glucose is "
                  "read against a different range and this table cannot tell "
                  "them apart"),
    Interval("hba1c", "mmol/mol", None, 39.0, "decision_threshold", "any",
             source="ADA: HbA1c below 5.7% (39 mmol/mol) is normal",
             note="a threshold for action, not a population reference interval"),

    # --- lipids: thresholds, not intervals -------------------------
    Interval("cholesterol", "mmol/L", None, 5.2, "decision_threshold", "any",
             source="common desirable total cholesterol target",
             note="a treatment target, not an abnormality boundary"),
    Interval("ldl", "mmol/L", None, 3.4, "decision_threshold", "any",
             source="common desirable LDL target",
             note="the right target depends on overall cardiovascular risk and "
                  "is a clinician's decision, not this table's"),
    Interval("hdl", "mmol/L", 1.0, None, "decision_threshold", "male",
             source="common HDL target"),
    Interval("hdl", "mmol/L", 1.3, None, "decision_threshold", "female",
             source="common HDL target"),
    Interval("hdl", "mmol/L", 1.0, None, "decision_threshold", "any",
             source="common HDL target",
             note="sex not known; the lower (male) target is used, so a "
                  "borderline result in a woman may be missed"),
    Interval("triglycerides", "mmol/L", None, 1.7, "decision_threshold", "any",
             source="common fasting triglyceride target"),
)


def lookup(analyte: str, *, sex: str | None = None) -> Interval | None:
    """The fallback interval for ``analyte``, preferring a sex-specific one."""
    key = (analyte or "").strip().lower()
    wanted = (sex or "any").strip().lower()
    if wanted not in ("male", "female"):
        wanted = "any"

    candidates = [row for row in _TABLE if row.analyte == key]
    if not candidates:
        return None
    for row in candidates:
        if row.applies_to == wanted:
            return row
    for row in candidates:
        if row.applies_to == "any":
            return row
    return None


def known_analytes() -> list[str]:
    return sorted({row.analyte for row in _TABLE})
