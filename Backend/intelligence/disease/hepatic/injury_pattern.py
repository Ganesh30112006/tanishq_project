"""Level 3: which way a liver panel is abnormal.

A liver panel is not a test with a normal and an abnormal answer. Its
information is in the *shape*: transaminases raised out of proportion to
alkaline phosphatase points at the liver cells, and alkaline phosphatase
raised out of proportion to the transaminases points at the bile ducts. Those
two shapes lead to different next tests. A system that reported "abnormal
liver function" would have collapsed the only thing the panel says.

So the six level-2 enzyme findings are read together here, and the result is
hedged with ``PATTERN_SUGGESTIVE_OF_``. Neither detector names a disease, and
neither can: the two commonest causes of a hepatocellular pattern in this
population - fatty liver and chronic viral hepatitis - are indistinguishable
on this panel and are managed completely differently.

The proportion is judged with the R ratio, the standard way of doing it:
``(ALT / upper limit) / (ALP / upper limit)``. Above 5 is hepatocellular,
below 2 is cholestatic, and in between is mixed and named as such rather than
forced into one bucket.
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
from intelligence.findings.evidence import EvidenceSet, Measurement

#: The conventional R-ratio boundaries.
HEPATOCELLULAR_R = 5.0
CHOLESTATIC_R = 2.0

_POPULATION = (
    "Non-pregnant adults aged 18 and over. Alkaline phosphatase rises in "
    "normal pregnancy and in normal adolescence, which would push the ratio "
    "towards a cholestatic reading with a healthy liver."
)
_VALIDATION = (
    "The R ratio is the conventional way of describing the shape of a liver "
    "panel. Its behaviour on the reports this system actually receives has "
    "never been measured, and no gold-standard annotated set exists yet."
)
_CONFIDENCE = (
    "PROVISIONAL at best. The ratio describes a shape, not a cause, and the "
    "commonest causes of each shape cannot be told apart on this panel. "
    "INSUFFICIENT when either enzyme is missing or has no upper limit to "
    "scale against, because the ratio cannot be formed at all."
)
_EXCLUSIONS = (
    "AST also comes from muscle and from red cells, so hard exercise and a "
    "haemolysed sample raise it with a normal liver.",
    "Alkaline phosphatase also comes from bone and placenta, so adolescence, "
    "pregnancy and bone conditions raise it with a normal liver.",
    "The ratio is conventionally formed from ALT. A panel that prints only "
    "AST gives a less reliable ratio.",
)
_OUT_OF_DOMAIN = (
    "Do not apply in pregnancy or under 18.",
    "Never name a liver disease. Fatty liver and chronic viral hepatitis "
    "produce the same hepatocellular shape and are managed completely "
    "differently.",
    "Never comment on alcohol intake from these results.",
)


def _contract(*, code: str, label: str, minimum: str) -> EvidenceContract:
    return EvidenceContract(
        code=code,
        version="1.0.0",
        level=EvidenceLevel.CONDITION_LIKELIHOOD,
        label=label,
        category="hepatic",
        required_evidence=(
            EvidenceRequirement(
                key="alt", why="the transaminase side of the ratio"
            ),
            EvidenceRequirement(
                key="alp", why="the cholestatic side of the ratio"
            ),
        ),
        optional_evidence=(
            EvidenceRequirement(
                key="ggt",
                why="a raised GGT alongside a raised ALP supports a liver "
                    "source rather than a bone one",
                required=False,
            ),
            EvidenceRequirement(
                key="bilirubin_total",
                why="bilirubin indicates how much the pattern matters, though "
                    "it does not decide its direction",
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
        references=("The R ratio as used in DILI and general hepatology",),
    )


HEPATOCELLULAR_CONTRACT = _contract(
    code="PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY",
    label="Liver panel shaped towards the liver cells",
    minimum=(
        "An ALT and an ALP, each with an upper reference limit, where the ALT "
        "is raised and the R ratio is above 5. One raised enzyme is never "
        "enough - the shape is a comparison between two."
    ),
)

CHOLESTATIC_CONTRACT = _contract(
    code="PATTERN_SUGGESTIVE_OF_CHOLESTASIS",
    label="Liver panel shaped towards the bile ducts",
    minimum=(
        "An ALT and an ALP, each with an upper reference limit, where the ALP "
        "is raised and the R ratio is below 2. One raised enzyme is never "
        "enough - the shape is a comparison between two."
    ),
)


def _fold(measurement: Measurement) -> float | None:
    """How many times the upper reference limit a value sits at."""
    high = measurement.reference_high
    if high is None or high <= 0 or measurement.value is None:
        return None
    return measurement.value / high


@dataclass(frozen=True, slots=True)
class LiverShapeDetector:
    contract: EvidenceContract
    #: "hepatocellular" or "cholestatic"
    direction: str

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        alt = evidence.measurement("alt")
        alp = evidence.measurement("alp")
        if alt is None and alp is None:
            # Not a liver panel: nothing to say at all.
            return None

        driver = alt if self.direction == "hepatocellular" else alp
        if driver is None or not driver.comparable or not driver.is_high:
            # The enzyme this shape is named for is not raised.
            return None

        used: list[EvidenceRef] = [
            m.to_ref() for m in (alt, alp) if m is not None
        ]
        for optional in ("ggt", "bilirubin_total"):
            extra = evidence.measurement(optional)
            if extra is not None:
                used.append(extra.to_ref())

        missing = [name for name, m in (("alt", alt), ("alp", alp)) if m is None]
        alt_fold = _fold(alt) if alt is not None else None
        alp_fold = _fold(alp) if alp is not None else None
        if alt_fold is None or alp_fold is None or alp_fold == 0:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=used,
                evidence_missing=missing or [
                    "an upper reference limit for both ALT and ALP, without "
                    "which the two cannot be compared"
                ],
                caveats=[
                    "The shape of a liver panel is a comparison between two "
                    "enzymes. One of them is missing or has no limit to scale "
                    "against, so no shape can be described.",
                ],
            )

        ratio = alt_fold / alp_fold
        matches = (
            ratio > HEPATOCELLULAR_R if self.direction == "hepatocellular"
            else ratio < CHOLESTATIC_R
        )
        if not matches:
            return build_finding(
                self.contract,
                confidence=Confidence.INSUFFICIENT,
                evidence_used=used,
                evidence_missing=[],
                caveats=[
                    f"The R ratio is {ratio:.1f}, which is between the "
                    f"conventional boundaries of {CHOLESTATIC_R:.0f} and "
                    f"{HEPATOCELLULAR_R:.0f}. This is a mixed picture and is "
                    f"not forced into either shape.",
                ],
            )

        caveats = [f"R ratio {ratio:.1f}."]
        ggt = evidence.measurement("ggt")
        # A missing GGT only weakens the cholestatic reading. It is what
        # separates a liver source from a bone one for a raised alkaline
        # phosphatase, and it says nothing about a hepatocellular shape - so
        # it is only reported as missing where its absence actually costs
        # something.
        missing_ggt = self.direction == "cholestatic" and ggt is None
        if self.direction == "cholestatic":
            if ggt is None:
                caveats.append(
                    "A GGT would help separate a liver source from a bone "
                    "source for the raised alkaline phosphatase. It is not on "
                    "this report."
                )
            elif not ggt.is_high:
                caveats.append(
                    "The GGT is not raised, which argues for a bone source "
                    "rather than a liver one."
                )
        return build_finding(
            self.contract,
            confidence=Confidence.PROVISIONAL,
            evidence_used=used,
            evidence_missing=["ggt"] if missing_ggt else [],
            caveats=caveats,
        )


HEPATOCELLULAR = LiverShapeDetector(
    contract=HEPATOCELLULAR_CONTRACT, direction="hepatocellular"
)
CHOLESTATIC = LiverShapeDetector(
    contract=CHOLESTATIC_CONTRACT, direction="cholestatic"
)

DETECTORS = (HEPATOCELLULAR, CHOLESTATIC)
