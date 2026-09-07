"""Level-2 renal patterns.

Each of these says that one kidney number is outside its range on one report.
None of them says the kidneys are damaged, and none of them may: every one of
these values moves with hydration, with an acute illness, with a scan done the
previous day and with common medicines, and every one of those recovers.

The distinction the whole framework exists to hold is at its sharpest here.
``REDUCED_EGFR_PATTERN`` is a fact about a report. Chronic kidney disease is a
fact about ninety days, which is why the level-3 detector that eventually
names it declares ``EvidenceTemporality.HISTORICAL`` and cannot assert
anything from a single report even if someone writes it that way.
"""
from __future__ import annotations

from intelligence.findings.base import ThresholdDetector, pattern_contract

_VALIDATION = (
    "The rule is a direct comparison against the report's own reference range "
    "or a published staging boundary, and has not been measured against a "
    "clinician-annotated set of reports in this system, so its precision and "
    "recall here are unknown."
)
_POLICY = (
    "SUPPORTED when the laboratory printed its own reference range for the "
    "analyte; PROVISIONAL when a general adult range had to be assumed, when "
    "the patient's sex is unknown for a sex-specific analyte, or when the "
    "comparison is against a guideline staging boundary rather than a "
    "reference interval."
)
_MOMENT = (
    "Every value in this panel moves with hydration and with acute illness. "
    "A single report describes the moment the sample was taken and cannot "
    "distinguish a temporary change from a lasting one.",
)

CREATININE_ELEVATION = ThresholdDetector(
    contract=pattern_contract(
        code="CREATININE_ELEVATION_PATTERN",
        label="Raised creatinine",
        category="renal",
        analyte="creatinine",
        why="serum creatinine above its reference interval",
        minimum_evidence="A creatinine value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            *_MOMENT,
            "Creatinine tracks muscle mass, so a value inside the interval "
            "does not exclude reduced kidney function in a small or elderly "
            "patient, and a value above it may be normal for a muscular one.",
        ),
    ),
    analytes=("creatinine",),
    direction="high",
)

REDUCED_EGFR = ThresholdDetector(
    contract=pattern_contract(
        code="REDUCED_EGFR_PATTERN",
        label="Reduced estimated GFR",
        category="renal",
        analyte="egfr",
        why="estimated GFR below the guideline staging boundary",
        minimum_evidence=(
            "An eGFR value. Note that the fallback comparison is against a "
            "staging boundary of 60 mL/min/1.73m2, not a reference interval."
        ),
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        references=("KDIGO 2012 CKD evaluation and management guideline",),
        exclusion_rules=(
            *_MOMENT,
            "A single low eGFR is not chronic kidney disease. Chronicity "
            "requires the abnormality to persist for at least ninety days, "
            "which no single report can establish.",
            "eGFR equations differ, and a report that does not name the "
            "equation cannot be compared reliably with an earlier one.",
        ),
    ),
    analytes=("egfr",),
    direction="low",
)

UREA_ELEVATION = ThresholdDetector(
    contract=pattern_contract(
        code="UREA_ELEVATION_PATTERN",
        label="Raised blood urea",
        category="renal",
        analyte=("urea", "bun"),
        why="blood urea, or blood urea nitrogen, above its reference interval",
        minimum_evidence=(
            "A urea or blood urea nitrogen value with a reference interval. "
            "The two are separate analytes because the same number in mg/dL "
            "means different amounts of urea, but either satisfies this rule."
        ),
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            *_MOMENT,
            "Urea moves with hydration far more than creatinine does, and "
            "rises with a high protein intake and with bleeding into the gut, "
            "so it is the less specific of the two.",
        ),
    ),
    analytes=("urea", "bun"),
    direction="high",
)

ALBUMINURIA = ThresholdDetector(
    contract=pattern_contract(
        code="ALBUMINURIA_PATTERN",
        label="Albumin in the urine",
        category="renal",
        analyte="urine_albumin_creatinine_ratio",
        why="urine albumin-to-creatinine ratio above the guideline boundary",
        minimum_evidence=(
            "A urine albumin-to-creatinine ratio. The fallback comparison is "
            "against the KDIGO A1/A2 boundary of 30 mg/g, a staging threshold."
        ),
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        references=("KDIGO albuminuria categories A1-A3",),
        exclusion_rules=(
            "Fever, hard exercise, a urine infection and menstruation all "
            "raise the ratio for days and are not visible on the report.",
            "Persistent albuminuria requires confirmation on a second or third "
            "sample over three to six months. A single raised ratio is not it.",
        ),
    ),
    analytes=("urine_albumin_creatinine_ratio",),
    direction="high",
)

DETECTORS = (CREATININE_ELEVATION, REDUCED_EGFR, UREA_ELEVATION, ALBUMINURIA)
