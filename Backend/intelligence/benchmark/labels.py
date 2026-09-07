"""Turning several clinicians' answers into the one label a score needs.

The rule is short and the reason it is short matters:

* the annotators agree -> that is the label;
* they disagree and a third adjudicated -> the ruling is the label;
* they disagree and nobody adjudicated -> **there is no label**. The item is
  excluded from that code's score and counted.

The third case is the one worth defending. Taking a majority, or taking the
first reader, or taking the more cautious answer would all produce a label, and
all of them would turn a case two clinicians could not agree on into a case the
detector is measured against as though it were settled. Disagreement between
readers is itself a measurement - a code with a high disagreement rate is a
code whose definition is not sharp enough to score - and it is destroyed by
being resolved automatically.

The rate is reported, and it is one of the promotion requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from intelligence.benchmark.schema import (
    Adjudication,
    BenchmarkItem,
    ConditionSupport,
    Determination,
    ReportAnnotation,
)


class LabelSource(str, Enum):  # noqa: UP042 - str mixin for reporting
    #: Every annotator gave the same answer.
    UNANIMOUS = "UNANIMOUS"
    #: They differed and a named adjudicator ruled.
    ADJUDICATED = "ADJUDICATED"
    #: They differed and nobody ruled. Not scoreable.
    UNRESOLVED = "UNRESOLVED"
    #: Nobody thought the code applied to this report.
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class Label:
    code: str
    source: LabelSource
    #: The agreed determination for a level-2 finding, when there is one.
    determination: Determination | None = None
    #: The agreed support for a level-3 condition, when there is one.
    support: ConditionSupport | None = None
    #: What the annotators actually said, kept for the disagreement report.
    answers: tuple[str, ...] = ()

    @property
    def scoreable(self) -> bool:
        return self.source in (LabelSource.UNANIMOUS, LabelSource.ADJUDICATED)


def _resolve(
    code: str,
    answers: list[str],
    ruling: str | None,
) -> tuple[LabelSource, str | None]:
    if not answers:
        return LabelSource.NOT_APPLICABLE, None
    if len(set(answers)) == 1:
        return LabelSource.UNANIMOUS, answers[0]
    if ruling is not None:
        return LabelSource.ADJUDICATED, ruling
    return LabelSource.UNRESOLVED, None


def finding_label(item: BenchmarkItem, code: str) -> Label:
    answers = [
        annotation.finding(code).determination.value
        for annotation in item.annotations
        if annotation.finding(code) is not None
    ]
    ruled = _ruling_for(item.adjudication, code, kind="finding")
    source, agreed = _resolve(code, answers, ruled)
    return Label(
        code=code,
        source=source,
        determination=Determination(agreed) if agreed is not None else None,
        answers=tuple(answers),
    )


def condition_label(item: BenchmarkItem, code: str) -> Label:
    answers = [
        annotation.condition(code).support.value
        for annotation in item.annotations
        if annotation.condition(code) is not None
    ]
    ruled = _ruling_for(item.adjudication, code, kind="condition")
    source, agreed = _resolve(code, answers, ruled)
    return Label(
        code=code,
        source=source,
        support=ConditionSupport(agreed) if agreed is not None else None,
        answers=tuple(answers),
    )


def _ruling_for(
    adjudication: Adjudication | None, code: str, *, kind: str
) -> str | None:
    if adjudication is None:
        return None
    if kind == "finding":
        found = adjudication.finding(code)
        return found.determination.value if found is not None else None
    found = adjudication.condition(code)
    return found.support.value if found is not None else None


def review_label(item: BenchmarkItem) -> Label:
    """Whether the report needed a person, resolved the same way."""
    answers = [str(a.human_review_required) for a in item.annotations]
    source, agreed = _resolve("HUMAN_REVIEW_REQUIRED", answers, None)
    return Label(
        code="HUMAN_REVIEW_REQUIRED",
        source=source,
        answers=tuple(answers),
    )


def disagreements(item: BenchmarkItem) -> dict[str, tuple[str, ...]]:
    """Codes the annotators answered differently, and what they each said."""
    out: dict[str, tuple[str, ...]] = {}
    for code in item.applicable_finding_codes:
        label = finding_label(item, code)
        if len(set(label.answers)) > 1:
            out[code] = label.answers
    for code in item.applicable_condition_codes:
        label = condition_label(item, code)
        if len(set(label.answers)) > 1:
            out[code] = label.answers
    return out


def annotator_ids(annotations: tuple[ReportAnnotation, ...]) -> tuple[str, ...]:
    return tuple(sorted(a.annotator_id for a in annotations))
