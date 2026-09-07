"""Level-2 liver patterns.

Six separate findings rather than one "abnormal liver function" pattern. That
is deliberate: which enzymes rise together is the whole of the clinical
information a liver panel carries. ALT and AST rising together points
somewhere quite different from ALP and GGT rising together, and collapsing
them into a single derangement would discard the only thing the panel says.

Reading the combination is a level-3 question. It is not answered here, and no
detector in this module names a liver disease - the two commonest causes of a
mildly raised ALT in this population cannot be told apart on this panel, and
the difference between them matters enormously to the patient.
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
    "PROVISIONAL when a general adult range had to be assumed, or when the "
    "patient's sex is unknown for a sex-specific analyte. The upper limits "
    "for ALT, AST and GGT all differ by sex."
)
_PANEL = (
    "A single enzyme above its range says very little. What the panel means "
    "depends on which enzymes rose together and by how much, which is a "
    "level-3 question this finding does not answer.",
)


def _enzyme(code: str, label: str, analyte: str, description: str,
            *extra: str) -> ThresholdDetector:
    return ThresholdDetector(
        contract=pattern_contract(
            code=code,
            label=label,
            category="hepatic",
            analyte=analyte,
            why=f"{description} above its reference interval",
            minimum_evidence=f"A {description} value with a reference interval.",
            confidence_policy=_POLICY,
            validation_note=_VALIDATION,
            exclusion_rules=(*_PANEL, *extra),
        ),
        analytes=(analyte,),
        direction="high",
    )


ALT_ELEVATION = _enzyme(
    "ALT_ELEVATION_PATTERN", "Raised ALT (SGPT)", "alt", "ALT (SGPT)",
    "A mildly raised ALT is common and frequently settles on a repeat "
    "sample; a normal ALT does not exclude liver disease, including cirrhosis.",
)

AST_ELEVATION = _enzyme(
    "AST_ELEVATION_PATTERN", "Raised AST (SGOT)", "ast", "AST (SGOT)",
    "AST also comes from muscle and from red cells, so hard exercise before "
    "the test and a haemolysed sample both raise it with a normal liver.",
)

ALP_ELEVATION = _enzyme(
    "ALP_ELEVATION_PATTERN", "Raised alkaline phosphatase", "alp",
    "alkaline phosphatase",
    "Alkaline phosphatase also comes from bone and placenta, so it is raised "
    "in normal adolescence and in normal pregnancy. Separating a liver source "
    "from a bone source usually needs the GGT.",
)

GGT_ELEVATION = _enzyme(
    "GGT_ELEVATION_PATTERN", "Raised GGT", "ggt", "GGT",
    "GGT is sensitive and not specific. It is raised by many common medicines "
    "and by fatty liver, and treating it as a test of alcohol intake is a "
    "well-known error.",
)

BILIRUBIN_ELEVATION = _enzyme(
    "BILIRUBIN_ELEVATION_PATTERN", "Raised bilirubin", "bilirubin_total",
    "total bilirubin",
    "Gilbert's syndrome affects roughly one person in twenty, is harmless, "
    "needs no treatment and produces exactly this result, especially during "
    "fasting or illness.",
    "A total bilirubin alone cannot be split into its conjugated and "
    "unconjugated fractions, and that split is what separates the harmless "
    "causes from the ones that matter.",
)

LOW_ALBUMIN = ThresholdDetector(
    contract=pattern_contract(
        code="LOW_ALBUMIN_PATTERN",
        label="Low albumin",
        category="hepatic",
        analyte="albumin",
        why="serum albumin below its reference interval",
        minimum_evidence="An albumin value with a reference interval.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            *_PANEL,
            "Albumin falls in any acute illness or inflammation regardless of "
            "nutrition, so a low value in an unwell patient is expected and is "
            "not evidence of malnutrition or of liver disease.",
            "A low albumin lowers the total calcium on the same panel without "
            "changing the ionised calcium, so a calcium flagged low alongside "
            "it may be explained entirely by this.",
        ),
    ),
    analytes=("albumin",),
    direction="low",
)

DETECTORS = (
    ALT_ELEVATION, AST_ELEVATION, ALP_ELEVATION, GGT_ELEVATION,
    BILIRUBIN_ELEVATION, LOW_ALBUMIN,
)
