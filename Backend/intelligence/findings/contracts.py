"""The one contract every finding and disease detector implements.

Four levels, and nothing may skip one:

==== ============================ =========================================
1    ``LAB_FINDING``              a measured value against its reference
                                  range: ``Hb 9.8 g/dL -> BELOW``
2    ``CLINICAL_ABNORMALITY``     a named pattern: ``ANEMIA_PATTERN``
3    ``CONDITION_LIKELIHOOD``     a combination of evidence:
                                  ``POSSIBLE_IRON_DEFICIENCY_ANEMIA``
4    ``RISK_MODEL``               validated features into a governed model
==== ============================ =========================================

The levels exist to make it *structurally impossible* to go from one abnormal
number to a disease. :meth:`EvidenceContract.__post_init__` enforces that:

* a level-2 code is named as a pattern, never as a disease;
* a level-3 code is hedged (``POSSIBLE_`` / ``SUSPECTED_``) and needs at least
  two pieces of evidence, so a single value can never reach level 3;
* levels 3 and 4 always require human review;
* a level-4 detector must already be clinically approved, which in this system
  means a governed ``ModelVersion`` in Django - a risk model cannot be created
  by writing a Python class;
* a detector that has never been measured against a gold standard must say so,
  in every result it emits.

That last one matters most. A rule copied from a textbook is a hypothesis about
this system's data until somebody measures it here. Marking it
``NOT_VALIDATED`` costs nothing and is the difference between a tool that knows
what it has demonstrated and one that does not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class EvidenceLevel(int, Enum):  # noqa: UP042 - int mixin so levels can be compared
    LAB_FINDING = 1
    CLINICAL_ABNORMALITY = 2
    CONDITION_LIKELIHOOD = 3
    RISK_MODEL = 4


class DetectorValidation(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    #: The rule is written from published clinical criteria and has never been
    #: measured against annotated data in this system.
    NOT_VALIDATED = "NOT_VALIDATED"
    #: Measured against a clinician-reviewed gold-standard set here.
    BENCHMARKED = "BENCHMARKED"
    #: Benchmarked *and* carried through the Django governance lifecycle with a
    #: named approver. Required for anything at level 4.
    CLINICALLY_APPROVED = "CLINICALLY_APPROVED"


class EvidenceTemporality(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    """How much of a patient's timeline a detector needs to be entitled to its
    conclusion.

    This exists because "abnormal now" and "abnormal for three months" are
    different clinical statements, and only the second one is a chronic
    disease. An eGFR of 55 on one report is a low eGFR; chronic kidney disease
    needs the same abnormality to persist for at least ninety days. Without
    this field a detector could quietly turn a dehydrated patient's Tuesday
    into a lifelong diagnosis, and nothing in the code would object.

    A detector declares what it needs; the evidence set declares what it
    actually holds; the engine refuses to let a detector assert anything it
    was not given the timeline for.
    """

    #: One report, one moment. Every level-2 pattern is this by definition.
    SINGLE_REPORT = "SINGLE_REPORT"
    #: The same analyte measured more than once, to tell a transient
    #: abnormality from a persistent one.
    REPEATED_MEASUREMENT = "REPEATED_MEASUREMENT"
    #: Repeated measurement plus a minimum elapsed time - the shape that
    #: chronicity criteria take.
    HISTORICAL = "HISTORICAL"
    #: Different analytes drawn from different reports, correlated. A blood
    #: count from one visit read alongside iron studies from another.
    CROSS_REPORT = "CROSS_REPORT"


class Confidence(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    #: Every required piece of evidence was present and pointed the same way.
    SUPPORTED = "SUPPORTED"
    #: The required evidence was present but something weakens it - a borderline
    #: value, a conflicting optional input, an assumed reference range.
    PROVISIONAL = "PROVISIONAL"
    #: Not enough evidence to say anything. The finding names what is missing
    #: and asserts nothing.
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class EvidenceRequirement:
    #: Canonical analyte name, or a finding code for detectors that build on
    #: lower-level findings (``ANEMIA_PATTERN``).
    key: str
    why: str
    required: bool = True
    #: True when ``key`` names another finding rather than a measurement.
    is_finding: bool = False


_HEDGES = ("POSSIBLE_", "SUSPECTED_", "PATTERN_SUGGESTIVE_OF_")


@dataclass(frozen=True, slots=True)
class EvidenceContract:
    """What a detector needs, what it may conclude, and what stands behind it."""

    code: str
    version: str
    level: EvidenceLevel
    label: str
    category: str
    required_evidence: tuple[EvidenceRequirement, ...]
    minimum_evidence: str
    valid_population: str
    confidence_policy: str
    validation_status: DetectorValidation
    #: "all" - every required item must be present. "any" - at least one must
    #: be, which is how a panel-level pattern (dyslipidaemia) is expressed
    #: without inventing a fake analyte to hang the requirement on.
    required_evidence_mode: str = "all"
    #: How much of the patient's timeline this detector needs. Anything beyond
    #: a single report must say exactly what it needs in
    #: ``temporality_requirement``, and the engine will not let it assert
    #: anything until the evidence set actually holds that.
    temporality: EvidenceTemporality = EvidenceTemporality.SINGLE_REPORT
    temporality_requirement: str = ""
    validation_note: str = ""
    optional_evidence: tuple[EvidenceRequirement, ...] = ()
    exclusion_rules: tuple[str, ...] = ()
    out_of_domain_rules: tuple[str, ...] = ()
    human_review_required: bool = True
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.upper():
            raise ValueError(f"{self.code!r}: codes are UPPER_SNAKE_CASE")
        if not self.version or not self.label or not self.category:
            raise ValueError(f"{self.code}: version, label and category are required")

        if self.level is EvidenceLevel.CLINICAL_ABNORMALITY and not self.code.endswith(
            "_PATTERN"
        ):
            raise ValueError(
                f"{self.code}: a level-2 finding names a pattern, not a disease. "
                f"Call it <SOMETHING>_PATTERN."
            )
        if self.level is EvidenceLevel.CONDITION_LIKELIHOOD:
            if not self.code.startswith(_HEDGES):
                raise ValueError(
                    f"{self.code}: a level-3 finding is a hypothesis and must be "
                    f"named as one - start it with one of {_HEDGES}."
                )
            if len(self.required_evidence) + len(self.optional_evidence) < 2:
                raise ValueError(
                    f"{self.code}: level 3 requires a combination of evidence. "
                    f"A single value may not reach a condition likelihood."
                )
        if (
            self.level is EvidenceLevel.CLINICAL_ABNORMALITY
            and self.temporality is not EvidenceTemporality.SINGLE_REPORT
        ):
            raise ValueError(
                f"{self.code}: a level-2 pattern is an observation on one "
                f"report. Whether it persists is a level-3 question, so it "
                f"cannot be asked for here."
            )
        if (
            self.temporality is not EvidenceTemporality.SINGLE_REPORT
            and not self.temporality_requirement.strip()
        ):
            raise ValueError(
                f"{self.code}: a detector needing {self.temporality.value} must "
                f"say exactly what timeline it needs, so the result can name "
                f"what was missing when it is not available"
            )
        if self.level >= EvidenceLevel.CONDITION_LIKELIHOOD and not self.human_review_required:
            raise ValueError(
                f"{self.code}: level {self.level.value} always requires human review"
            )
        if (
            self.level is EvidenceLevel.RISK_MODEL
            and self.validation_status is not DetectorValidation.CLINICALLY_APPROVED
        ):
            raise ValueError(
                f"{self.code}: a level-4 risk model must be CLINICALLY_APPROVED - "
                f"it needs a governed ModelVersion behind it, not just a class."
            )
        if (
            self.validation_status is DetectorValidation.NOT_VALIDATED
            and not self.validation_note.strip()
        ):
            raise ValueError(
                f"{self.code}: an unvalidated detector must say what has not been "
                f"measured about it"
            )
        for name in ("minimum_evidence", "valid_population", "confidence_policy"):
            if not getattr(self, name).strip():
                raise ValueError(f"{self.code}: {name} must be stated")
        if not self.required_evidence:
            raise ValueError(f"{self.code}: at least one required evidence item")
        if self.required_evidence_mode not in ("all", "any"):
            raise ValueError(
                f"{self.code}: required_evidence_mode is 'all' or 'any', "
                f"got {self.required_evidence_mode!r}"
            )

    @property
    def identity(self) -> str:
        return f"{self.code}:{self.version}"


# --- what a detector was given, and what it produced -----------------
@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One piece of evidence, traceable to where it came from."""

    key: str
    kind: str                       # "measurement" | "finding"
    value: float | None = None
    unit: str = ""
    reference_text: str = ""
    reference_source: str = ""      # "report" | "fallback-table" | ""
    reference_status: str = ""
    page: int | None = None
    section: str = ""
    source_text: str = ""
    char_span: tuple[int, int] | None = None
    text_source: str = ""
    ocr_provider: str = ""


@dataclass(slots=True)
class Finding:
    code: str
    label: str
    level: EvidenceLevel
    category: str
    detector: str                   # code:version
    confidence: Confidence
    validation_status: DetectorValidation
    human_review_required: bool
    explanation: str
    evidence_used: list[EvidenceRef] = field(default_factory=list)
    evidence_missing: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def asserts_anything(self) -> bool:
        return self.confidence is not Confidence.INSUFFICIENT


@runtime_checkable
class Detector(Protocol):
    contract: EvidenceContract

    def evaluate(self, evidence) -> Finding | None:
        """Return a Finding, or ``None`` when this detector has nothing to say.

        ``None`` means "not applicable / nothing abnormal here". A detector that
        *is* applicable but lacks evidence returns a Finding with
        ``Confidence.INSUFFICIENT`` naming what is missing - silence and "I
        cannot tell" are different answers.
        """
        ...
