"""What a clinician is asked, and the shape their answer takes.

Every detector in this system is ``NOT_VALIDATED``: the rules are copied from
published clinical criteria and nobody has measured what they do on the reports
this system actually receives. This package is the apparatus for changing that,
and it is deliberately built before there is any data to put through it, so the
measurement is designed by someone who does not yet know what it will say.

The questions are the ones a clinician can actually answer from a report:

======================== ==============================================
Finding present?         PRESENT / ABSENT / CANNOT_DETERMINE
Evidence sufficient?     SUFFICIENT / INSUFFICIENT
Condition supported?     SUPPORTED / NOT_SUPPORTED / INSUFFICIENT
Alternative explanation? free text, and the reason it is plausible
Human review required?   yes / no
======================== ==============================================

``CANNOT_DETERMINE`` is not a gap in the annotation. It is a real answer, and
the case where the clinician cannot tell either is exactly the case where the
system abstaining is *correct* rather than unhelpful - so it is scored
separately rather than dropped.

Two annotators read every report and a third adjudicates disagreements. A
report where they disagreed and nobody adjudicated is excluded from scoring
and counted, because quietly taking the majority would turn measured
disagreement into invisible agreement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

#: Bump when the questions change. A corpus records which version it was
#: annotated under, and sets annotated under different versions are not pooled.
ANNOTATION_SCHEMA_VERSION = "benchmark-annotation-1"


class Determination(str, Enum):  # noqa: UP042 - str mixin is the file format
    """Is the finding present on this report?"""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    #: The report does not contain enough to answer. A real answer, not a gap.
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class EvidenceSufficiency(str, Enum):  # noqa: UP042 - str mixin is the file format
    """Was there enough on the report to reach the determination?"""

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class ConditionSupport(str, Enum):  # noqa: UP042 - str mixin is the file format
    """Do the results support the condition likelihood?"""

    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    #: Not enough on the report to say either way.
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class FindingAnnotation:
    """One clinician's answer about one level-2 finding code."""

    code: str
    determination: Determination
    evidence_sufficient: EvidenceSufficiency
    #: Something other than the finding that would explain these numbers -
    #: a haemolysed sample, dehydration, a recent illness. Free text, because
    #: the point is to capture what a checklist would have missed.
    alternative_explanation: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.upper():
            raise ValueError(f"{self.code!r}: codes are UPPER_SNAKE_CASE")
        if (
            self.determination is Determination.CANNOT_DETERMINE
            and self.evidence_sufficient is EvidenceSufficiency.SUFFICIENT
        ):
            raise ValueError(
                f"{self.code}: the evidence cannot be sufficient and the "
                f"determination undecidable at the same time"
            )


@dataclass(frozen=True, slots=True)
class ConditionAnnotation:
    """One clinician's answer about one level-3 condition code."""

    code: str
    support: ConditionSupport
    alternative_explanation: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.upper():
            raise ValueError(f"{self.code!r}: codes are UPPER_SNAKE_CASE")


@dataclass(frozen=True, slots=True)
class ReportAnnotation:
    """Everything one clinician recorded about one report."""

    report_id: str
    report_type: str
    annotator_id: str
    annotated_on: date
    #: The codes this report could reasonably carry, decided by the annotator
    #: from what the report contains. Every one of them must have an answer
    #: below, and nothing may be answered that is not declared here.
    applicable_finding_codes: tuple[str, ...]
    applicable_condition_codes: tuple[str, ...]
    findings: tuple[FindingAnnotation, ...]
    conditions: tuple[ConditionAnnotation, ...]
    #: Would this report need a person to look at it before anything was acted
    #: on? Measured separately from the findings, because a system can get
    #: every finding right and still route the report wrongly.
    human_review_required: bool
    #: The values on the report the annotator actually used, as printed.
    supporting_evidence: tuple[str, ...] = ()
    #: What the annotator wanted and the report did not have.
    missing_evidence: tuple[str, ...] = ()
    schema_version: str = ANNOTATION_SCHEMA_VERSION
    note: str = ""

    def __post_init__(self) -> None:
        if not self.report_id or not self.annotator_id:
            raise ValueError("a report id and an annotator id are required")
        if self.schema_version != ANNOTATION_SCHEMA_VERSION:
            raise ValueError(
                f"{self.report_id}: annotated under {self.schema_version}, this "
                f"code speaks {ANNOTATION_SCHEMA_VERSION}. Sets annotated under "
                f"different question sets are not pooled."
            )
        self._check("finding", self.applicable_finding_codes,
                    [f.code for f in self.findings])
        self._check("condition", self.applicable_condition_codes,
                    [c.code for c in self.conditions])

    def _check(self, kind: str, declared: tuple[str, ...], answered: list[str]) -> None:
        if len(set(answered)) != len(answered):
            raise ValueError(f"{self.report_id}: a {kind} code is answered twice")
        missing = set(declared) - set(answered)
        if missing:
            raise ValueError(
                f"{self.report_id}: declared {kind} codes {sorted(missing)} "
                f"applicable but did not answer them. An unanswered applicable "
                f"code would silently drop out of the measurement."
            )
        extra = set(answered) - set(declared)
        if extra:
            raise ValueError(
                f"{self.report_id}: answered {kind} codes {sorted(extra)} that "
                f"were not declared applicable"
            )

    def finding(self, code: str) -> FindingAnnotation | None:
        return next((f for f in self.findings if f.code == code), None)

    def condition(self, code: str) -> ConditionAnnotation | None:
        return next((c for c in self.conditions if c.code == code), None)


@dataclass(frozen=True, slots=True)
class Adjudication:
    """A third clinician's ruling where the first two disagreed."""

    adjudicator_id: str
    adjudicated_on: date
    findings: tuple[FindingAnnotation, ...] = ()
    conditions: tuple[ConditionAnnotation, ...] = ()
    #: Why they disagreed. This is the most valuable free text in the corpus:
    #: it is where the cases the rules get wrong describe themselves.
    disagreement_reason: str = ""

    def __post_init__(self) -> None:
        if not self.adjudicator_id:
            raise ValueError("an adjudication needs a named adjudicator")
        if not self.findings and not self.conditions:
            raise ValueError("an adjudication that rules on nothing is not one")
        if not self.disagreement_reason.strip():
            raise ValueError(
                "an adjudication must record why the annotators disagreed - "
                "that reason is the most useful thing in the corpus"
            )

    def finding(self, code: str) -> FindingAnnotation | None:
        return next((f for f in self.findings if f.code == code), None)

    def condition(self, code: str) -> ConditionAnnotation | None:
        return next((c for c in self.conditions if c.code == code), None)


@dataclass(frozen=True, slots=True)
class BenchmarkItem:
    """One report, everything recorded about it, and the ruling if any."""

    report_id: str
    report_type: str
    #: SHA-256 of the document the annotators read, so a corpus cannot drift
    #: away from the files it describes.
    source_sha256: str
    annotations: tuple[ReportAnnotation, ...]
    adjudication: Adjudication | None = None
    #: Free text about the report itself - a photographed page, an unusual
    #: layout, a laboratory that prints no reference ranges.
    note: str = ""

    def __post_init__(self) -> None:
        if not self.annotations:
            raise ValueError(f"{self.report_id}: no annotations")
        annotators = [a.annotator_id for a in self.annotations]
        if len(set(annotators)) != len(annotators):
            raise ValueError(
                f"{self.report_id}: the same annotator appears twice. Two reads "
                f"by one person are one read."
            )
        for annotation in self.annotations:
            if annotation.report_id != self.report_id:
                raise ValueError(
                    f"{self.report_id}: carries an annotation for "
                    f"{annotation.report_id}"
                )

    @property
    def annotator_count(self) -> int:
        return len(self.annotations)

    @property
    def applicable_finding_codes(self) -> set[str]:
        """The union: if either reader thought a code applied, it is scored."""
        return {
            code for a in self.annotations for code in a.applicable_finding_codes
        }

    @property
    def applicable_condition_codes(self) -> set[str]:
        return {
            code for a in self.annotations for code in a.applicable_condition_codes
        }


@dataclass(slots=True)
class Corpus:
    """A set of annotated reports, scored as one."""

    corpus_id: str
    items: list[BenchmarkItem] = field(default_factory=list)
    description: str = ""
    schema_version: str = ANNOTATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        seen = [item.report_id for item in self.items]
        if len(set(seen)) != len(seen):
            raise ValueError(f"{self.corpus_id}: a report id appears twice")

    def __len__(self) -> int:
        return len(self.items)
