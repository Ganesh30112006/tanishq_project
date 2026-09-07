"""Level 3: thyroid patterns that need TSH and free T4 read together.

Reading the two together is the entire point of the panel, and it is exactly
the step a level-2 pattern may not take. A raised TSH with a low free T4 and a
raised TSH with a *normal* free T4 are different situations, managed
differently, and the difference is invisible unless something looks at both.

Both detectors here cap at PROVISIONAL, and neither ever reaches SUPPORTED.
Two reasons, and they are not formalities:

* thyroid function tests are unreliable during and shortly after any acute
  illness, and a report shows no illness;
* every guideline asks for the abnormality to be confirmed on a second sample
  before treatment, because a substantial share of raised TSH results are
  normal on a repeat.

The subclinical detector is also the one place in the system where a *normal*
result is required evidence. A normal free T4 is what makes the pattern
subclinical rather than overt, so its absence is missing evidence, not a
detail to be skipped over.
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

_POPULATION = (
    "Non-pregnant adults aged 18 and over who are not acutely unwell. The "
    "pregnancy intervals differ in every trimester, and acute illness makes "
    "thyroid results uninterpretable. A report shows neither."
)
_VALIDATION = (
    "The rule follows standard biochemical criteria. Its behaviour on the "
    "reports this system actually receives has never been measured, and no "
    "gold-standard annotated set exists yet."
)
_CONFIDENCE = (
    "PROVISIONAL at best, never SUPPORTED. Guidelines require confirmation on "
    "a second sample before the pattern means anything, and acute illness - "
    "which the report does not show - produces the same numbers. "
    "INSUFFICIENT when the free T4 is absent, because without it an overt and "
    "a subclinical picture cannot be told apart."
)
_EXCLUSIONS = (
    "Any acute or recent illness produces abnormal thyroid results that "
    "return to normal on recovery. The report does not show illness.",
    "Recovery from a recent illness raises TSH transiently.",
    "Several common medicines change these results, and the report does not "
    "list medicines.",
    "A substantial share of raised TSH results are normal on a repeat sample.",
)
_OUT_OF_DOMAIN = (
    "Do not apply in pregnancy or under 18.",
    "Never present this as a diagnosis, and never let it become a "
    "recommendation to start, stop or change thyroid medicine.",
)


def _contract(*, code: str, label: str, minimum: str) -> EvidenceContract:
    return EvidenceContract(
        code=code,
        version="1.0.0",
        level=EvidenceLevel.CONDITION_LIKELIHOOD,
        label=label,
        category="thyroid",
        required_evidence=(
            EvidenceRequirement(
                key="TSH_ELEVATION_PATTERN",
                why="a raised TSH is the entry criterion for both patterns",
                is_finding=True,
            ),
        ),
        optional_evidence=(
            EvidenceRequirement(
                key="free_t4",
                why="the free T4 is what separates an overt picture from a "
                    "subclinical one",
                required=False,
            ),
        ),
        minimum_evidence=minimum,
        valid_population=_POPULATION,
        confidence_policy=_CONFIDENCE,
        validation_status=DetectorValidation.NOT_VALIDATED,
        validation_note=_VALIDATION,
        exclusion_rules=_EXCLUSIONS,
        out_of_domain_rules=_OUT_OF_DOMAIN,
        human_review_required=True,
        references=("ATA/AACE guidelines for hypothyroidism in adults",),
    )


PRIMARY_CONTRACT = _contract(
    code="POSSIBLE_PRIMARY_HYPOTHYROIDISM",
    label="Pattern that may suggest an underactive thyroid gland",
    minimum=(
        "A raised TSH together with a free T4 below its reference interval. "
        "A raised TSH alone is not enough - without the free T4 the pattern "
        "cannot be told apart from a subclinical one."
    ),
)

SUBCLINICAL_CONTRACT = _contract(
    code="POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM",
    label="Pattern that may suggest a mildly underactive thyroid gland",
    minimum=(
        "A raised TSH together with a free T4 that is *inside* its reference "
        "interval. The normal free T4 is required evidence, not an absence: "
        "it is what makes the pattern subclinical."
    ),
)


@dataclass(frozen=True, slots=True)
class _HypothyroidDetector:
    contract: EvidenceContract
    #: True when a free T4 inside its interval is what this detector wants.
    wants_normal_t4: bool

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        raised_tsh = evidence.finding("TSH_ELEVATION_PATTERN")
        if raised_tsh is None or not raised_tsh.asserts_anything:
            # No raised TSH: neither pattern is in question at all.
            return None

        used: list[EvidenceRef] = [
            EvidenceRef(key="TSH_ELEVATION_PATTERN", kind="finding")
        ]
        free_t4 = evidence.measurement("free_t4")
        if free_t4 is None or not free_t4.comparable:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=used,
                evidence_missing=["a free T4 with a reference interval"],
                caveats=[
                    "A raised TSH on its own does not say whether the thyroid "
                    "hormone level is actually low. The free T4 is what "
                    "separates the two pictures.",
                ],
            )

        used.append(free_t4.to_ref())
        matches = (not free_t4.is_low) if self.wants_normal_t4 else free_t4.is_low
        if not matches:
            # The other detector of the pair is the one that applies here.
            return None

        return build_finding(
            self.contract,
            confidence=Confidence.PROVISIONAL,
            evidence_used=used,
            caveats=[
                "Confirmation on a second sample, taken at least a few weeks "
                "later, is required before this pattern means anything.",
                "Acute or recent illness produces the same results and is not "
                "visible on the report.",
            ],
        )


PRIMARY_HYPOTHYROIDISM = _HypothyroidDetector(
    contract=PRIMARY_CONTRACT, wants_normal_t4=False
)
SUBCLINICAL_HYPOTHYROIDISM = _HypothyroidDetector(
    contract=SUBCLINICAL_CONTRACT, wants_normal_t4=True
)

DETECTORS = (PRIMARY_HYPOTHYROIDISM, SUBCLINICAL_HYPOTHYROIDISM)
