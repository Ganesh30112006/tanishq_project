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

from intelligence.knowledge.provenance import (
    Applicability,
    Provenance,
    SourceType,
    ValidationStatus,
)

#: Bump when a bound changes; findings record which version they used.
RANGE_TABLE_VERSION = "adult-ranges-2"

#: What stands behind every interval here. The laboratory's own printed range
#: always wins over this table, and that preference is the point: these are
#: textbook averages, not this instrument's interval for this population.
PROVENANCE = Provenance(
    source_type=SourceType.LITERATURE,
    source="common adult laboratory intervals and published guideline thresholds",
    applicability=Applicability.UNKNOWN,
    validation_status=ValidationStatus.NOT_VALIDATED,
    what_would_validate_it=(
        "Reference intervals established on the population this system serves, "
        "on the instruments its reports come from. Until then the laboratory's "
        "own printed range is preferred wherever a report carries one, and any "
        "finding that fell back to this table says so."
    ),
)


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

    Interval("hematocrit", "%", 40.0, 52.0, "reference_interval", "male",
             source="common adult laboratory intervals"),
    Interval("hematocrit", "%", 36.0, 48.0, "reference_interval", "female",
             source="common adult laboratory intervals"),
    Interval("hematocrit", "%", 36.0, 52.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="sex not known; the wider interval is used"),
    Interval("rbc", "10^12/L", 4.5, 5.9, "reference_interval", "male",
             source="common adult laboratory intervals"),
    Interval("rbc", "10^12/L", 4.0, 5.2, "reference_interval", "female",
             source="common adult laboratory intervals"),
    Interval("rbc", "10^12/L", 4.0, 5.9, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="sex not known; the wider interval is used"),
    Interval("mch", "pg", 27.0, 33.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("mchc", "g/L", 320.0, 360.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("rdw", "%", 11.5, 14.5, "reference_interval", "any",
             source="common adult RDW-CV interval",
             note="this is RDW-CV as a percentage. RDW-SD is reported in "
                  "femtolitres, is a different quantity, and is deliberately "
                  "not read against this interval"),
    # The differential, as PERCENTAGES of the white cell count. A percentage
    # says nothing on its own about whether the absolute count is normal: a
    # raised lymphocyte percentage with a low total white count is a normal
    # lymphocyte count. No absolute-count interval is given for any of these.
    Interval("neutrophils", "%", 40.0, 75.0, "reference_interval", "any",
             source="common adult differential-count interval",
             note="a PERCENTAGE of white cells, not an absolute count"),
    Interval("lymphocytes", "%", 20.0, 45.0, "reference_interval", "any",
             source="common adult differential-count interval",
             note="a PERCENTAGE of white cells, not an absolute count"),
    Interval("monocytes", "%", 2.0, 10.0, "reference_interval", "any",
             source="common adult differential-count interval",
             note="a PERCENTAGE of white cells, not an absolute count"),
    Interval("basophils", "%", 0.0, 2.0, "reference_interval", "any",
             source="common adult differential-count interval",
             note="a PERCENTAGE of white cells, not an absolute count"),

    # --- glycaemia -------------------------------------------------
    # An unqualified "glucose" has NO fallback interval on purpose. A fasting
    # and a random sample are read against different numbers, and a report
    # that does not say which was taken cannot be read against either. The
    # value is carried, and the comparison is simply not made.
    Interval("fasting_glucose", "mmol/L", 3.9, 5.5, "reference_interval", "any",
             source="fasting plasma glucose, common laboratory interval"),
    Interval("random_glucose", "mmol/L", None, 7.8, "decision_threshold", "any",
             source="a random plasma glucose under 7.8 mmol/L is normal",
             note="a threshold for further testing, not a population interval; "
                  "it depends on how long ago the patient ate, which the "
                  "report does not say"),
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

    # --- renal -----------------------------------------------------
    Interval("creatinine", "umol/L", 62.0, 106.0, "reference_interval", "male",
             source="common adult laboratory intervals",
             note="creatinine tracks muscle mass, so the same number means "
                  "different things in a large young man and a small elderly "
                  "woman; a value inside the interval does not exclude "
                  "reduced kidney function"),
    Interval("creatinine", "umol/L", 44.0, 80.0, "reference_interval", "female",
             source="common adult laboratory intervals",
             note="creatinine tracks muscle mass; a value inside the interval "
                  "does not exclude reduced kidney function"),
    Interval("creatinine", "umol/L", 44.0, 106.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="sex not known; the wider interval is used, so a raised "
                  "creatinine in a woman may be missed"),
    Interval("egfr", "mL/min/1.73m2", 60.0, None, "decision_threshold", "any",
             source="KDIGO: eGFR below 60 mL/min/1.73m2 is the G3a boundary",
             note="a staging boundary, not a population reference interval. A "
                  "single low eGFR is not chronic kidney disease - chronicity "
                  "requires the abnormality to persist for at least 90 days"),
    Interval("urea", "mmol/L", 2.5, 7.1, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="urea rises with dehydration, a high protein intake and "
                  "gastrointestinal bleeding as well as with kidney disease"),
    Interval("bun", "mmol/L", 2.5, 7.1, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="blood urea nitrogen, not urea; the two differ by about "
                  "2.14x and are separate analytes here"),
    Interval("urine_albumin_creatinine_ratio", "mg/g", None, 30.0,
             "decision_threshold", "any",
             source="KDIGO: ACR below 30 mg/g is category A1",
             note="a staging boundary. A single raised ACR is not albuminuria; "
                  "confirmation on a second sample is required, and exercise, "
                  "fever, infection and menstruation all raise it transiently"),

    # --- liver -----------------------------------------------------
    Interval("alt", "U/L", 0.0, 41.0, "reference_interval", "male",
             source="common adult laboratory upper limits"),
    Interval("alt", "U/L", 0.0, 33.0, "reference_interval", "female",
             source="common adult laboratory upper limits"),
    Interval("alt", "U/L", 0.0, 41.0, "reference_interval", "any",
             source="common adult laboratory upper limits",
             note="sex not known; the higher (male) limit is used, so a mildly "
                  "raised ALT in a woman may be missed"),
    Interval("ast", "U/L", 0.0, 40.0, "reference_interval", "male",
             source="common adult laboratory upper limits"),
    Interval("ast", "U/L", 0.0, 32.0, "reference_interval", "female",
             source="common adult laboratory upper limits"),
    Interval("ast", "U/L", 0.0, 40.0, "reference_interval", "any",
             source="common adult laboratory upper limits",
             note="sex not known; the higher (male) limit is used"),
    Interval("alp", "U/L", 30.0, 120.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="alkaline phosphatase also comes from bone and placenta, so "
                  "it rises in adolescence, in pregnancy and in bone disease "
                  "with a completely normal liver"),
    Interval("ggt", "U/L", 0.0, 60.0, "reference_interval", "male",
             source="common adult laboratory upper limits"),
    Interval("ggt", "U/L", 0.0, 40.0, "reference_interval", "female",
             source="common adult laboratory upper limits"),
    Interval("ggt", "U/L", 0.0, 60.0, "reference_interval", "any",
             source="common adult laboratory upper limits",
             note="sex not known; the higher (male) limit is used"),
    Interval("bilirubin_total", "umol/L", 3.0, 21.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="Gilbert's syndrome is common and harmless and raises the "
                  "unconjugated bilirubin, especially during fasting or "
                  "illness"),
    Interval("bilirubin_direct", "umol/L", 0.0, 5.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("albumin", "g/L", 35.0, 50.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="albumin falls in acute illness and in inflammation without "
                  "any liver disease"),
    Interval("total_protein", "g/L", 60.0, 83.0, "reference_interval", "any",
             source="common adult laboratory intervals"),

    # --- thyroid ---------------------------------------------------
    Interval("tsh", "mIU/L", 0.4, 4.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="the pregnancy intervals are different in every trimester, "
                  "and TSH is unreliable during and shortly after any acute "
                  "illness"),
    Interval("free_t4", "pmol/L", 9.0, 19.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="assay methods differ enough that the laboratory's own "
                  "interval should be used whenever it is printed"),
    Interval("free_t3", "pmol/L", 3.5, 6.5, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="free T3 falls in any serious non-thyroidal illness; a low "
                  "value in an unwell patient usually means the illness, not "
                  "the thyroid"),

    # --- electrolytes ----------------------------------------------
    Interval("sodium", "mmol/L", 135.0, 145.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("potassium", "mmol/L", 3.5, 5.1, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="a haemolysed sample releases potassium from red cells and "
                  "is a common cause of a falsely high result"),
    Interval("chloride", "mmol/L", 98.0, 107.0, "reference_interval", "any",
             source="common adult laboratory intervals"),
    Interval("bicarbonate", "mmol/L", 22.0, 29.0, "reference_interval", "any",
             source="common adult laboratory intervals",
             note="bicarbonate falls in a sample left standing, so a mildly "
                  "low value on a routine panel is often an artefact"),
    Interval("calcium", "mmol/L", 2.15, 2.55, "reference_interval", "any",
             source="common adult total-calcium interval",
             note="this is TOTAL calcium, which follows albumin. A low albumin "
                  "lowers total calcium with no change in the ionised calcium "
                  "that actually matters, and this table cannot correct for it"),
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
