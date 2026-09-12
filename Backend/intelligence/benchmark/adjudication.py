"""Turning several annotators' answers into the one label a score needs.

Shared by both benchmarks, because the rule is the same whether two people are
disagreeing about a haemoglobin value or about whether a condition is
supported:

* they agree -> that is the label;
* they differ and a third adjudicated -> the ruling is the label;
* they differ and nobody adjudicated -> **there is no label**. The item is
  excluded from that field's score and counted.

The third case is the one worth defending. Taking a majority, taking the first
reader, or taking the more cautious answer would all produce a label, and all
of them would turn a case two people could not agree on into a case the system
is measured against as though it were settled.

Disagreement is itself a measurement. A field with a high disagreement rate is
a field whose definition is not sharp enough to score - which is a finding
about the annotation schema, and it is destroyed by being resolved
automatically. The rate is reported, and it is one of the promotion
requirements in both benchmarks.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LabelSource(str, Enum):  # noqa: UP042 - str mixin for reporting
    #: Every annotator gave the same answer.
    UNANIMOUS = "UNANIMOUS"
    #: They differed and a named adjudicator ruled.
    ADJUDICATED = "ADJUDICATED"
    #: They differed and nobody ruled. Not scoreable.
    UNRESOLVED = "UNRESOLVED"
    #: Nobody thought the field applied to this document.
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class Resolution:
    """What several annotators, taken together, established about one field."""

    key: str
    source: LabelSource
    #: The agreed answer, as the comparable token the callers use. ``None``
    #: whenever the source is not UNANIMOUS or ADJUDICATED.
    agreed: str | None = None
    #: What each annotator actually said, kept for the disagreement report.
    answers: tuple[str, ...] = ()

    @property
    def scoreable(self) -> bool:
        return self.source in (LabelSource.UNANIMOUS, LabelSource.ADJUDICATED)

    @property
    def disputed(self) -> bool:
        return len(set(self.answers)) > 1


def resolve(key: str, answers: list[str], ruling: str | None) -> Resolution:
    """Apply the rule above to one field's answers."""
    if not answers:
        return Resolution(key, LabelSource.NOT_APPLICABLE, answers=())
    if len(set(answers)) == 1:
        return Resolution(
            key, LabelSource.UNANIMOUS, answers[0], tuple(answers)
        )
    if ruling is not None:
        return Resolution(
            key, LabelSource.ADJUDICATED, ruling, tuple(answers)
        )
    return Resolution(key, LabelSource.UNRESOLVED, None, tuple(answers))
