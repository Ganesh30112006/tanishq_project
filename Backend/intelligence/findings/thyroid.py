"""Level-2 thyroid patterns.

TSH and free T4 are four separate findings, and combining them is deliberately
not done here. The pattern between them *is* the diagnosis - a raised TSH with
a normal free T4 and a raised TSH with a low free T4 are different situations
managed differently - so reading them together is a level-3 conclusion that
needs a hedged code, a combination contract and human review.

There is a second reason to keep them apart. Thyroid results are unreliable
during and shortly after any acute illness, and the intervals shift in every
trimester of pregnancy. A report shows neither. A level-2 finding that only
reports one number against one range is honest about that; a combined one that
named a thyroid condition would not be.
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
    "PROVISIONAL when a general adult range had to be assumed. Free-hormone "
    "assays differ enough between laboratories that the printed range matters "
    "more here than for most analytes."
)
_CONTEXT = (
    "Thyroid results are unreliable during and shortly after any acute "
    "illness, and the reference intervals differ in every trimester of "
    "pregnancy. Neither is visible from the report.",
    "Reading TSH together with the free hormones is what names a thyroid "
    "condition. That combination is a level-3 conclusion and is not drawn "
    "here.",
)


def _thyroid(code: str, label: str, analyte: str, description: str,
             direction: str, *extra: str) -> ThresholdDetector:
    above_below = "above" if direction == "high" else "below"
    return ThresholdDetector(
        contract=pattern_contract(
            code=code,
            label=label,
            category="thyroid",
            analyte=analyte,
            why=f"{description} {above_below} its reference interval",
            minimum_evidence=f"A {description} value with a reference interval.",
            confidence_policy=_POLICY,
            validation_note=_VALIDATION,
            exclusion_rules=(*_CONTEXT, *extra),
        ),
        analytes=(analyte,),
        direction=direction,
    )


TSH_ELEVATION = _thyroid(
    "TSH_ELEVATION_PATTERN", "Raised TSH", "tsh", "TSH", "high",
    "TSH varies through the day and is highest at night, so the time the "
    "sample was taken affects the number.",
    "A raised TSH frequently returns to normal on a repeat sample, which is "
    "why a repeat is usual before anything is concluded.",
)

TSH_SUPPRESSION = _thyroid(
    "TSH_SUPPRESSION_PATTERN", "Low TSH", "tsh", "TSH", "low",
    "TSH is normally low in the first trimester of pregnancy.",
    "In a patient already taking thyroid hormone, a low TSH is a question "
    "about their dose rather than a new finding, and the report does not say "
    "whether they take it.",
)

LOW_FREE_T4 = _thyroid(
    "LOW_FREE_T4_PATTERN", "Low free T4", "free_t4", "free T4", "low",
    "Free T4 falls in any serious non-thyroidal illness, where it reflects the "
    "illness rather than the thyroid gland.",
)

HIGH_FREE_T4 = _thyroid(
    "HIGH_FREE_T4_PATTERN", "High free T4", "free_t4", "free T4", "high",
    "In a patient taking thyroxine, a sample drawn within a few hours of the "
    "tablet reads high without meaning anything.",
)

DETECTORS = (TSH_ELEVATION, TSH_SUPPRESSION, LOW_FREE_T4, HIGH_FREE_T4)
