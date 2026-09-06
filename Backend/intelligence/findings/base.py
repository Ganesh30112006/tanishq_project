"""Shared detector machinery, so a hundred detectors are not a hundred designs.

Most level-2 findings are the same shape: one analyte, one direction, one
named pattern. :class:`ThresholdDetector` is that shape, and a detector that
needs more (a combination, a ratio, a condition on age) implements
:class:`~intelligence.findings.contracts.Detector` directly and reuses
:func:`build_finding` for the parts that must not vary.

The parts that must not vary: every finding carries its detector identity and
version, its validation status, the traceable evidence it used, the evidence it
lacked, and an explanation drawn from the approved knowledge dictionary rather
than composed on the spot.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.findings.contracts import (
    Confidence,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRef,
    Finding,
)
from intelligence.findings.evidence import EvidenceSet, Measurement
from intelligence.knowledge import findings as KB


def build_finding(
    contract: EvidenceContract,
    *,
    confidence: Confidence,
    evidence_used: list[EvidenceRef] | None = None,
    evidence_missing: list[str] | None = None,
    caveats: list[str] | None = None,
) -> Finding:
    knowledge = KB.get(contract.code)
    if knowledge is None:
        raise KeyError(
            f"{contract.code} has no entry in the finding knowledge dictionary. "
            f"A detector may not invent its own explanation."
        )

    notes = list(caveats or [])
    notes.extend(knowledge.cautionary_notes)
    if contract.validation_status is DetectorValidation.NOT_VALIDATED:
        notes.append(
            "This rule has not been measured against annotated data in this "
            "system: " + contract.validation_note
        )
    if confidence is Confidence.INSUFFICIENT:
        explanation = (
            f"{knowledge.canonical_name}: not enough evidence to say. "
            f"{contract.minimum_evidence}"
        )
    else:
        explanation = knowledge.plain_explanation

    return Finding(
        code=contract.code,
        label=contract.label,
        level=contract.level,
        category=contract.category,
        detector=contract.identity,
        confidence=confidence,
        validation_status=contract.validation_status,
        human_review_required=contract.human_review_required,
        explanation=explanation,
        evidence_used=list(evidence_used or []),
        evidence_missing=list(evidence_missing or []),
        caveats=notes,
    )


def confidence_for(measurement: Measurement) -> tuple[Confidence, list[str]]:
    """How much a single comparison is worth, and why."""
    caveats: list[str] = []
    if measurement.reference_source == "report":
        return Confidence.SUPPORTED, caveats

    caveats.append(
        "The report did not print a reference range for "
        f"{measurement.analyte}, so a general adult range was assumed "
        f"({measurement.reference_text})."
    )
    if measurement.reference_note:
        caveats.append(measurement.reference_note)
    if measurement.reference_kind == "decision_threshold":
        caveats.append(
            "The number compared against is a treatment target, not a "
            "population reference range, so 'outside it' does not mean "
            "'abnormal'."
        )
    return Confidence.PROVISIONAL, caveats


@dataclass(frozen=True, slots=True)
class ThresholdDetector:
    """One analyte, one direction, one named pattern."""

    contract: EvidenceContract
    analyte: str
    direction: str  # "high" | "low"

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        measurement = evidence.measurement(self.analyte)
        if measurement is None:
            # Not applicable: this report does not contain the analyte at all.
            return None

        if not measurement.comparable:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=[measurement.to_ref()],
                evidence_missing=[f"a reference range for {self.analyte}"],
            )

        triggered = measurement.is_high if self.direction == "high" else measurement.is_low
        if not triggered:
            return None

        confidence, caveats = confidence_for(measurement)
        return build_finding(
            self.contract,
            confidence=confidence,
            evidence_used=[measurement.to_ref()],
            caveats=caveats,
        )


def pattern_contract(
    *,
    code: str,
    label: str,
    category: str,
    analyte: str,
    why: str,
    minimum_evidence: str,
    confidence_policy: str,
    validation_note: str,
    references: tuple[str, ...] = (),
    out_of_domain_rules: tuple[str, ...] = (),
    exclusion_rules: tuple[str, ...] = (),
) -> EvidenceContract:
    """A level-2 contract for a single-analyte pattern."""
    from intelligence.findings.contracts import EvidenceRequirement

    return EvidenceContract(
        code=code,
        version="1.0.0",
        level=EvidenceLevel.CLINICAL_ABNORMALITY,
        label=label,
        category=category,
        required_evidence=(EvidenceRequirement(key=analyte, why=why),),
        minimum_evidence=minimum_evidence,
        valid_population=(
            "Adults aged 18 and over. Paediatric and pregnancy reference "
            "intervals differ and are not modelled here."
        ),
        confidence_policy=confidence_policy,
        validation_status=DetectorValidation.NOT_VALIDATED,
        validation_note=validation_note,
        out_of_domain_rules=out_of_domain_rules
        or (
            "Do not apply to patients under 18 - the reference intervals differ.",
            "Do not apply in pregnancy - haematological and metabolic ranges shift.",
        ),
        exclusion_rules=exclusion_rules,
        human_review_required=True,
        references=references,
    )
