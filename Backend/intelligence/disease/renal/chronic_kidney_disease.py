"""Level 3: a pattern that may suggest chronic kidney disease.

This detector exists to be honest about something the rest of the system would
otherwise get wrong in a way nobody would notice.

The word in the name is *chronic*. KDIGO defines chronic kidney disease as an
abnormality of kidney structure or function **present for more than three
months**. That is not a stricter threshold on the same number - it is a
different kind of claim. An eGFR of 46 today is a low eGFR today. Dehydration,
an acute illness, a contrast scan the previous day and an anti-inflammatory
tablet all produce exactly that number, and all of them recover.

A detector that fired on one report would be right often enough to look
useful. The people it was wrong about would be told they had a lifelong
condition on the basis of a bad week, and nothing in the output would have
distinguished them from the people it was right about.

So the contract declares what it needs about time - repeated measurements, a
ninety-day window, ordered dates, and the abnormality itself present at both
ends - and the engine evaluates that before letting the detector assert
anything. The detector below does not check the timeline at all. It used to,
and that was the problem: the check would have had to be rewritten, correctly,
by every future detector with a chronicity criterion in its name.

The distinction the contract holds is the one that is easiest to lose:
*longitudinal data is not a persistent abnormality*. A patient whose eGFR was
92 a year ago and is 58 today has a year of data and a new abnormality.
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
from intelligence.findings.temporal import (
    Subject,
    TemporalContract,
    TemporalRequirement,
)

#: KDIGO's chronicity criterion, in days.
CHRONICITY_DAYS = 90

#: Which analyte carries each entry criterion, for the caveats below.
_ANALYTE_FOR = {
    "REDUCED_EGFR_PATTERN": "egfr",
    "ALBUMINURIA_PATTERN": "urine_albumin_creatinine_ratio",
}

CONTRACT = EvidenceContract(
    code="POSSIBLE_CHRONIC_KIDNEY_DISEASE",
    version="1.0.0",
    level=EvidenceLevel.CONDITION_LIKELIHOOD,
    label="Pattern that may suggest chronic kidney disease",
    category="renal",
    required_evidence=(
        EvidenceRequirement(
            key="REDUCED_EGFR_PATTERN",
            why="a reduced filtration rate is one of the two entry criteria",
            is_finding=True,
        ),
        EvidenceRequirement(
            key="ALBUMINURIA_PATTERN",
            why="albumin in the urine is the other entry criterion, and it can "
                "be present with a normal filtration rate",
            is_finding=True,
        ),
    ),
    required_evidence_mode="any",
    optional_evidence=(
        EvidenceRequirement(
            key="creatinine",
            why="the measurement the filtration rate was estimated from",
            required=False,
        ),
    ),
    minimum_evidence=(
        "A reduced eGFR or albuminuria, AND evidence that the same "
        "abnormality was present at least ninety days earlier. One report can "
        "never satisfy this."
    ),
    valid_population=(
        "Non-pregnant adults aged 18 and over, not acutely unwell. Pregnancy "
        "changes the filtration rate substantially, and an acute illness "
        "invalidates the chronicity assumption entirely."
    ),
    confidence_policy=(
        "PROVISIONAL at best. Even with ninety days of history, a single "
        "system reading laboratory reports cannot exclude an acute-on-chronic "
        "picture, cannot see the imaging or the urine sediment, and cannot "
        "stage without both an eGFR and an albumin-to-creatinine ratio. "
        "INSUFFICIENT whenever the timeline is not there, which is the usual "
        "case."
    ),
    validation_status=DetectorValidation.NOT_VALIDATED,
    validation_note=(
        "The rule follows the KDIGO definition. Its behaviour on the reports "
        "this system actually receives has never been measured, and no "
        "gold-standard annotated set exists yet."
    ),
    temporal=TemporalContract(
        requirements=frozenset({
            TemporalRequirement.REPEATED_MEASUREMENTS,
            TemporalRequirement.TIME_WINDOW,
            TemporalRequirement.PERSISTENT_ABNORMALITY,
            TemporalRequirement.ORDERED_SEQUENCE,
        }),
        subjects=(
            Subject("egfr", "below",
                    "a reduced filtration rate must be shown to have lasted"),
            Subject("urine_albumin_creatinine_ratio", "above",
                    "albuminuria must be shown to have lasted"),
        ),
        minimum_observations=2,
        minimum_window_days=CHRONICITY_DAYS,
        subject_mode="any",
        rationale=(
            "KDIGO defines chronic kidney disease as an abnormality present "
            "for more than three months. A single report cannot distinguish "
            "it from a temporary fall in kidney function, and the two are "
            "managed completely differently."
        ),
    ),
    exclusion_rules=(
        "Acute kidney injury produces the same numbers and recovers. "
        "Dehydration, an acute illness, a scan with contrast dye and common "
        "anti-inflammatory tablets are all invisible on the report.",
        "A raised albumin-to-creatinine ratio is transiently raised by fever, "
        "hard exercise, a urine infection and menstruation.",
        "eGFR equations differ, and two reports using different equations are "
        "not directly comparable even when both are available.",
    ),
    out_of_domain_rules=(
        "Do not apply in pregnancy or under 18.",
        "Never present this as a diagnosis and never give a CKD stage. "
        "Staging needs both an eGFR and an albumin-to-creatinine ratio, and "
        "assigning a stage is a clinical act.",
    ),
    human_review_required=True,
    references=(
        "KDIGO 2012 clinical practice guideline for the evaluation and "
        "management of chronic kidney disease",
    ),
)


@dataclass(frozen=True, slots=True)
class ChronicKidneyDiseaseDetector:
    contract: EvidenceContract = CONTRACT

    def evaluate(self, evidence: EvidenceSet) -> Finding | None:
        entry_criteria = [
            code for code in ("REDUCED_EGFR_PATTERN", "ALBUMINURIA_PATTERN")
            if (found := evidence.finding(code)) is not None
            and found.asserts_anything
        ]
        if not entry_criteria:
            # Neither entry criterion is present: nothing to say at all.
            return None

        used: list[EvidenceRef] = [
            EvidenceRef(key=code, kind="finding") for code in entry_criteria
        ]
        creatinine = evidence.measurement("creatinine")
        if creatinine is not None:
            used.append(creatinine.to_ref())

        both = len(entry_criteria) == 2
        caveats = [
            "Present on both entry criteria." if both
            else f"Present on one entry criterion: {entry_criteria[0]}.",
            "Acute-on-chronic kidney disease produces the same picture and "
            "cannot be excluded from laboratory reports alone.",
        ]
        for code in entry_criteria:
            series = evidence.series_for(_ANALYTE_FOR[code])
            if series is not None and series.count >= 2:
                caveats.append(
                    f"{series.analyte} was already outside its range "
                    f"{series.span_days} days ago: {series.describe()}."
                )
                caveats.extend(series.caveats)
        if not both:
            caveats.append(
                "Staging needs both an eGFR and an albumin-to-creatinine "
                "ratio. Only one is available, so no stage is given."
            )
        return build_finding(
            self.contract,
            confidence=Confidence.PROVISIONAL,
            evidence_used=used,
            caveats=caveats,
        )



CHRONIC_KIDNEY_DISEASE = ChronicKidneyDiseaseDetector()

DETECTORS = (CHRONIC_KIDNEY_DISEASE,)
