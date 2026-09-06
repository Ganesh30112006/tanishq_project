"""Level 3: a pattern that may suggest iron-deficiency anaemia.

This is the first detector above the pattern level, and it is here mostly to
prove that the level boundary holds. A low haemoglobin alone cannot reach it -
the contract refuses to register a level-3 detector with fewer than two pieces
of evidence, and this one will not fire without a supporting index.

On most reports that supporting index is absent, and the honest output is a
finding with ``INSUFFICIENT`` confidence that names MCV and ferritin as the
missing evidence. A system that instead announced "iron deficiency" from a
haemoglobin of 9.8 would look far more useful and would be wrong often enough
to hurt someone: thalassaemia trait produces the same blood count, and iron
given for the wrong reason is harmful.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.findings.base import build_finding
from intelligence.findings.contracts import (
    Confidence,
    DetectorValidation,
    EvidenceContract,
    EvidenceLevel,
    EvidenceRef,
    EvidenceRequirement,
    Finding,
)
from intelligence.findings.evidence import EvidenceSet

CONTRACT = EvidenceContract(
    code="POSSIBLE_IRON_DEFICIENCY_ANEMIA",
    version="1.0.0",
    level=EvidenceLevel.CONDITION_LIKELIHOOD,
    label="Pattern that may suggest iron-deficiency anaemia",
    category="hematology",
    required_evidence=(
        EvidenceRequirement(
            key="ANEMIA_PATTERN",
            why="there must be an anaemia to explain before a cause is considered",
            is_finding=True,
        ),
    ),
    optional_evidence=(
        EvidenceRequirement(
            key="MICROCYTOSIS_PATTERN",
            why="small red cells are compatible with iron deficiency",
            required=False,
            is_finding=True,
        ),
        EvidenceRequirement(
            key="ferritin",
            why="a low ferritin is the most specific routine marker of low iron stores",
            required=False,
        ),
    ),
    minimum_evidence=(
        "An anaemia pattern PLUS at least one supporting index - a low MCV or a "
        "low ferritin. Haemoglobin alone is never enough."
    ),
    valid_population=(
        "Non-pregnant adults aged 18 and over. Pregnancy, childhood and known "
        "haemoglobinopathy each change the interpretation and are not modelled."
    ),
    confidence_policy=(
        "SUPPORTED only when ferritin is low, which is the specific marker. A "
        "low MCV alone gives PROVISIONAL, because thalassaemia trait and "
        "anaemia of chronic disease produce the same picture. When neither "
        "index is on the report the result is INSUFFICIENT and names what is "
        "missing."
    ),
    validation_status=DetectorValidation.NOT_VALIDATED,
    validation_note=(
        "The rule follows standard haematology teaching. Its sensitivity and "
        "specificity on the reports this system actually receives have never "
        "been measured, and no gold-standard annotated set exists yet."
    ),
    exclusion_rules=(
        "Ferritin is an acute-phase reactant and rises with inflammation, so a "
        "normal ferritin does not exclude iron deficiency in an unwell patient.",
        "Thalassaemia trait gives a low haemoglobin with a low MCV and normal "
        "iron stores; this detector cannot tell the two apart.",
    ),
    out_of_domain_rules=(
        "Do not apply in pregnancy or under 18.",
        "Never present this as a diagnosis, and never let it become a "
        "recommendation to take iron. Unexplained iron deficiency in an adult "
        "requires the source of blood loss to be investigated.",
    ),
    human_review_required=True,
    references=(
        "WHO: haemoglobin thresholds for anaemia",
        "BSH guideline on the laboratory diagnosis of functional iron deficiency",
    ),
)


@dataclass(frozen=True, slots=True)
class IronDeficiencyDetector:
    contract: EvidenceContract = CONTRACT

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        anemia = evidence.finding("ANEMIA_PATTERN")
        if anemia is None or not anemia.asserts_anything:
            # No anaemia to explain: this detector has nothing to say at all.
            return None

        used: list[EvidenceRef] = [EvidenceRef(key="ANEMIA_PATTERN", kind="finding")]
        supporting: list[str] = []
        missing: list[str] = []

        microcytosis = evidence.finding("MICROCYTOSIS_PATTERN")
        mcv = evidence.measurement("mcv")
        if microcytosis is not None and microcytosis.asserts_anything:
            supporting.append("MICROCYTOSIS_PATTERN")
            used.append(EvidenceRef(key="MICROCYTOSIS_PATTERN", kind="finding"))
        elif mcv is None:
            missing.append("mcv")

        ferritin = evidence.measurement("ferritin")
        ferritin_low = ferritin is not None and ferritin.is_low
        if ferritin is None:
            missing.append("ferritin")
        else:
            used.append(ferritin.to_ref())
            if ferritin_low:
                supporting.append("ferritin below its reference interval")

        if not supporting:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=used,
                evidence_missing=missing or [
                    "a supporting index - the MCV and ferritin on this report "
                    "do not point to iron deficiency"
                ],
            )

        confidence = Confidence.SUPPORTED if ferritin_low else Confidence.PROVISIONAL
        caveats = [f"Supported by: {', '.join(supporting)}."]
        if not ferritin_low:
            caveats.append(
                "Ferritin, the specific marker of iron stores, is not available "
                "on this report, so this remains one of several explanations."
            )
        return build_finding(
            self.contract,
            confidence=confidence,
            evidence_used=used,
            evidence_missing=missing,
            caveats=caveats,
        )


IRON_DEFICIENCY = IronDeficiencyDetector()

DETECTORS = (IRON_DEFICIENCY,)
