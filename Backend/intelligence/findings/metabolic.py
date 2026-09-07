"""Level-2 metabolic patterns.

Two of these compare against a *decision threshold* rather than a reference
interval - HbA1c and the lipids. That distinction is carried into the finding:
being above a treatment target is not the same as being abnormal, and the
caveat says so rather than leaving a reader to infer it.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.findings.base import (
    ThresholdDetector,
    build_finding,
    confidence_for,
    pattern_contract,
)
from intelligence.findings.contracts import (
    Confidence,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRequirement,
    Finding,
)
from intelligence.findings.evidence import EvidenceSet

_VALIDATION = (
    "The rule is a threshold comparison taken from published guidance and has "
    "not been measured against a clinician-annotated set of reports here."
)
_POLICY = (
    "SUPPORTED when the laboratory printed its own range; PROVISIONAL when a "
    "guideline threshold or a general adult range had to be assumed."
)

HYPERGLYCEMIA = ThresholdDetector(
    contract=pattern_contract(
        code="HYPERGLYCEMIA_PATTERN",
        label="High blood glucose",
        category="metabolic",
        version="1.1.0",
        analyte=("fasting_glucose", "random_glucose", "glucose"),
        why="a glucose value above the range that applies to the sample taken",
        minimum_evidence=(
            "A glucose value that says which sample it is - fasting or random "
            "- with a range to compare it against. An unqualified glucose has "
            "no range and produces no finding."
        ),
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        exclusion_rules=(
            "A fasting and a random sample are read against different numbers. "
            "A report that labels neither resolves to an unqualified glucose, "
            "for which there is deliberately no fallback range, so no finding "
            "is produced rather than the wrong one.",
        ),
    ),
    analytes=("fasting_glucose", "random_glucose", "glucose"),
    direction="high",
)

ELEVATED_HBA1C = ThresholdDetector(
    contract=pattern_contract(
        code="ELEVATED_HBA1C_PATTERN",
        label="Raised HbA1c",
        category="metabolic",
        analyte="hba1c",
        why="HbA1c above the level usually taken as normal",
        minimum_evidence="An HbA1c value.",
        confidence_policy=_POLICY,
        validation_note=_VALIDATION,
        references=("ADA Standards of Care: HbA1c below 5.7% is normal",),
        exclusion_rules=(
            "HbA1c is unreliable in anaemia, recent transfusion or blood loss, "
            "and in haemoglobin variants - all common in this population and "
            "none of them visible from an HbA1c result alone.",
        ),
    ),
    analytes=("hba1c",),
    direction="high",
)

_LIPIDS = (
    ("cholesterol", "high"),
    ("ldl", "high"),
    ("triglycerides", "high"),
    ("hdl", "low"),
)

DYSLIPIDEMIA_CONTRACT = EvidenceContract(
    code="DYSLIPIDEMIA_PATTERN",
    version="1.0.0",
    level=EvidenceLevel.CLINICAL_ABNORMALITY,
    label="Lipid results outside the usual targets",
    category="metabolic",
    required_evidence=tuple(
        EvidenceRequirement(key=analyte, why=f"{analyte} against its usual target")
        for analyte, _ in _LIPIDS
    ),
    required_evidence_mode="any",
    minimum_evidence=(
        "At least one of total cholesterol, LDL, HDL or triglycerides, with a "
        "target to compare it against."
    ),
    valid_population=(
        "Adults aged 18 and over, not pregnant. Lipid targets in pregnancy and "
        "in childhood are different and are not modelled here."
    ),
    confidence_policy=(
        "Always at most PROVISIONAL when the comparison uses a guideline "
        "target rather than a laboratory reference interval, because the right "
        "target depends on the patient's overall cardiovascular risk."
    ),
    validation_status=DetectorValidation.NOT_VALIDATED,
    validation_note=(
        "Threshold comparisons taken from common guideline targets; not "
        "measured against annotated reports in this system."
    ),
    exclusion_rules=(
        "Triglycerides require a fasting sample; a non-fasting triglyceride is "
        "routinely higher and the report may not say which was taken.",
    ),
    out_of_domain_rules=(
        "Do not apply under 18 or in pregnancy.",
        "Never convert this finding into a cardiovascular risk estimate. Risk "
        "is a level-4 question answered only by the governed model.",
    ),
    human_review_required=True,
)


@dataclass(frozen=True, slots=True)
class DyslipidemiaDetector:
    """A panel-level pattern: any one lipid outside its target triggers it."""

    contract: EvidenceContract = DYSLIPIDEMIA_CONTRACT

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        present = [
            (analyte, direction, evidence.measurement(analyte))
            for analyte, direction in _LIPIDS
            if evidence.measurement(analyte) is not None
        ]
        if not present:
            return None      # not a lipid report; nothing to say

        comparable = [(a, d, m) for a, d, m in present if m.comparable]
        if not comparable:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=[m.to_ref() for _, _, m in present],
                evidence_missing=["a target or reference range for any lipid"],
            )

        triggered = [
            (a, m) for a, d, m in comparable
            if (m.is_high if d == "high" else m.is_low)
        ]
        if not triggered:
            return None

        caveats: list[str] = []
        confidence = Confidence.SUPPORTED
        for _, measurement in triggered:
            item_confidence, item_caveats = confidence_for(measurement)
            if item_confidence is Confidence.PROVISIONAL:
                confidence = Confidence.PROVISIONAL
            caveats.extend(item_caveats)
            if measurement.reference_kind == "decision_threshold":
                confidence = Confidence.PROVISIONAL

        caveats.append(
            "Outside target: " + ", ".join(analyte for analyte, _ in triggered) + "."
        )
        return build_finding(
            self.contract,
            confidence=confidence,
            evidence_used=[m.to_ref() for _, _, m in comparable],
            caveats=caveats,
        )


DYSLIPIDEMIA = DyslipidemiaDetector()

DETECTORS = (HYPERGLYCEMIA, ELEVATED_HBA1C, DYSLIPIDEMIA)
