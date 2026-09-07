"""Level-2 electrolyte patterns.

This is the one place in the system where a number can be a genuine emergency,
and also the place where a wrong number is commonest. A haemolysed sample, a
tourniquet left on too long, a drip running into the same arm and a tube left
standing overnight each produce a result that looks alarming and is an
artefact.

Both halves of that have to survive into the output. A finding that only
carried the urgency would frighten patients over haemolysed tubes; one that
only carried the doubt would be useless. So each contract states the artefact
that most often fakes it, and no detector here estimates urgency - that is a
clinical judgement about a patient, not a comparison against a range.
"""
from __future__ import annotations

from intelligence.findings.base import ThresholdDetector, pattern_contract

_VALIDATION = (
    "The rule is a direct comparison against the report's own reference range "
    "and has not been measured against a clinician-annotated set of reports in "
    "this system, so its precision and recall here are unknown."
)
_POLICY = (
    "SUPPORTED when the laboratory printed its own reference range; "
    "PROVISIONAL when a general adult range had to be assumed."
)
_SAMPLE = (
    "How the sample was drawn and handled moves these numbers as much as the "
    "patient does. A result outside the range is often settled by a repeat on "
    "a fresh sample.",
    "This finding says a value is outside its range. It does not and may not "
    "estimate how urgent that is, which depends on the patient, on how fast "
    "the value changed, and on findings no report contains.",
)


def _ion(code: str, label: str, analyte: str, description: str,
         direction: str, *extra: str) -> ThresholdDetector:
    above_below = "above" if direction == "high" else "below"
    return ThresholdDetector(
        contract=pattern_contract(
            code=code,
            label=label,
            category="electrolytes",
            analyte=analyte,
            why=f"{description} {above_below} its reference interval",
            minimum_evidence=f"A {description} value with a reference interval.",
            confidence_policy=_POLICY,
            validation_note=_VALIDATION,
            exclusion_rules=(*_SAMPLE, *extra),
        ),
        analytes=(analyte,),
        direction=direction,
    )


HYPONATREMIA = _ion(
    "HYPONATREMIA_PATTERN", "Low sodium", "sodium", "serum sodium", "low",
    "A very high blood glucose or a very high triglyceride level makes sodium "
    "read falsely low on some analysers.",
)

HYPERNATREMIA = _ion(
    "HYPERNATREMIA_PATTERN", "High sodium", "sodium", "serum sodium", "high",
    "A raised sodium usually reflects water balance rather than salt intake, "
    "and the report carries nothing about either.",
)

HYPOKALEMIA = _ion(
    "HYPOKALEMIA_PATTERN", "Low potassium", "potassium", "serum potassium",
    "low",
    "A low potassium often accompanies a low magnesium, which most routine "
    "panels do not measure.",
)

HYPERKALEMIA = _ion(
    "HYPERKALEMIA_PATTERN", "High potassium", "potassium", "serum potassium",
    "high",
    "Haemolysis is the single commonest cause of a raised potassium on a "
    "routine sample. Many laboratories flag it; a report that carries no flag "
    "is not evidence the sample was clean, and this detector cannot see one.",
)

HYPOCALCEMIA = _ion(
    "HYPOCALCEMIA_PATTERN", "Low calcium", "calcium", "total serum calcium",
    "low",
    "Total calcium follows albumin. A low albumin lowers it without changing "
    "the ionised calcium that matters, and this system does not correct for "
    "albumin, so a low total calcium beside a low albumin may mean nothing.",
)

HYPERCALCEMIA = _ion(
    "HYPERCALCEMIA_PATTERN", "High calcium", "calcium", "total serum calcium",
    "high",
    "A tight tourniquet during the blood draw raises total calcium, and so "
    "does dehydration.",
)

LOW_BICARBONATE = _ion(
    "LOW_BICARBONATE_PATTERN", "Low bicarbonate", "bicarbonate",
    "serum bicarbonate", "low",
    "Bicarbonate falls in a sample left standing before testing, so a mildly "
    "low value on a routine panel is frequently an artefact.",
    "Whether the blood is actually acidotic is a question for a blood gas, "
    "not for a routine panel, and this finding does not answer it.",
)

DETECTORS = (
    HYPONATREMIA, HYPERNATREMIA, HYPOKALEMIA, HYPERKALEMIA,
    HYPOCALCEMIA, HYPERCALCEMIA, LOW_BICARBONATE,
)
