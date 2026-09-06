"""Level-2 haematology patterns.

Each of these says one thing: a measured value sits outside its range, and here
is the name clinicians give that observation. None of them names a cause. The
codes end in ``_PATTERN`` because the contract refuses to register a level-2
finding that reads like a diagnosis.
"""
from __future__ import annotations

from intelligence.findings.base import ThresholdDetector, pattern_contract

_VALIDATION = (
    "The rule is a direct comparison against the report's own reference range "
    "and has not been measured against a clinician-annotated set of reports in "
    "this system, so its precision and recall here are unknown."
)
_POLICY = (
    "SUPPORTED when the laboratory printed its own reference range for the "
    "analyte; PROVISIONAL when a general adult range had to be assumed, or "
    "when the patient's sex is unknown for a sex-specific analyte."
)

ANEMIA = ThresholdDetector(
    contract=pattern_contract(
        code="ANEMIA_PATTERN",
        label="Low haemoglobin (anaemia pattern)",
        category="hematology",
        analyte="hemoglobin",
        why="haemoglobin below its reference interval is the definition of the pattern",
        minimum_evidence="A haemoglobin value with a reference interval to compare it against.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        references=("WHO haemoglobin thresholds for anaemia",),
        exclusion_rules=(
            "A dilutional low value after fluids, and a haemodiluted sample, "
            "produce the same number and cannot be excluded from a report alone.",
        ),
    ),
    analyte="hemoglobin",
    direction="low",
)

POLYCYTHEMIA = ThresholdDetector(
    contract=pattern_contract(
        code="POLYCYTHEMIA_PATTERN",
        label="High haemoglobin",
        category="hematology",
        analyte="hemoglobin",
        why="haemoglobin above its reference interval",
        minimum_evidence="A haemoglobin value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=("Dehydration raises haemoglobin without any change in red-cell mass.",),
    ),
    analyte="hemoglobin",
    direction="high",
)

LEUKOCYTOSIS = ThresholdDetector(
    contract=pattern_contract(
        code="LEUKOCYTOSIS_PATTERN",
        label="High white blood cell count",
        category="hematology",
        analyte="wbc",
        why="total white cell count above its reference interval",
        minimum_evidence="A total white cell count with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
    ),
    analyte="wbc",
    direction="high",
)

LEUKOPENIA = ThresholdDetector(
    contract=pattern_contract(
        code="LEUKOPENIA_PATTERN",
        label="Low white blood cell count",
        category="hematology",
        analyte="wbc",
        why="total white cell count below its reference interval",
        minimum_evidence="A total white cell count with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
    ),
    analyte="wbc",
    direction="low",
)

THROMBOCYTOPENIA = ThresholdDetector(
    contract=pattern_contract(
        code="THROMBOCYTOPENIA_PATTERN",
        label="Low platelet count",
        category="hematology",
        analyte="platelets",
        why="platelet count below its reference interval",
        minimum_evidence="A platelet count with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            "Platelet clumping in the sample tube gives a falsely low count and "
            "is only excluded on a blood film, which a report may not include.",
        ),
    ),
    analyte="platelets",
    direction="low",
)

THROMBOCYTOSIS = ThresholdDetector(
    contract=pattern_contract(
        code="THROMBOCYTOSIS_PATTERN",
        label="High platelet count",
        category="hematology",
        analyte="platelets",
        why="platelet count above its reference interval",
        minimum_evidence="A platelet count with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
    ),
    analyte="platelets",
    direction="high",
)

EOSINOPHILIA = ThresholdDetector(
    contract=pattern_contract(
        code="EOSINOPHILIA_PATTERN",
        label="Raised eosinophil count",
        category="hematology",
        analyte="eosinophils",
        why="eosinophil count or percentage above its reference interval",
        minimum_evidence="An eosinophil value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            "A percentage and an absolute count are different measurements; a "
            "raised percentage with a normal absolute count is not eosinophilia, "
            "and a report that gives only a percentage cannot settle that.",
        ),
    ),
    analyte="eosinophils",
    direction="high",
)

MICROCYTOSIS = ThresholdDetector(
    contract=pattern_contract(
        code="MICROCYTOSIS_PATTERN",
        label="Small red blood cells (low MCV)",
        category="hematology",
        analyte="mcv",
        why="mean corpuscular volume below its reference interval",
        minimum_evidence="An MCV value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
    ),
    analyte="mcv",
    direction="low",
)

MACROCYTOSIS = ThresholdDetector(
    contract=pattern_contract(
        code="MACROCYTOSIS_PATTERN",
        label="Large red blood cells (high MCV)",
        category="hematology",
        analyte="mcv",
        why="mean corpuscular volume above its reference interval",
        minimum_evidence="An MCV value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
    ),
    analyte="mcv",
    direction="high",
)

DETECTORS = (
    ANEMIA, POLYCYTHEMIA, LEUKOCYTOSIS, LEUKOPENIA,
    THROMBOCYTOPENIA, THROMBOCYTOSIS, EOSINOPHILIA,
    MICROCYTOSIS, MACROCYTOSIS,
)
