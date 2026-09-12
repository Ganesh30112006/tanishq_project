"""What a detector must be shown about time before it may conclude anything.

The distinction this module exists to hold:

    longitudinal data  !=  persistent abnormality

A patient with two years of results has longitudinal data. A patient whose
eGFR was 92 a year ago and is 58 today has a *year* of data and a *new*
abnormality, and calling that chronic kidney disease would be wrong in a way
nothing downstream could detect. Chronicity is not a long date range; it is the
same abnormality at both ends of one.

The first version of this check lived inside the chronic kidney disease
detector, which worked and would not have survived the next detector someone
wrote. So the requirement is declared in the contract and checked generically:

    TemporalContract(
        requirements={REPEATED_MEASUREMENTS, TIME_WINDOW,
                      PERSISTENT_ABNORMALITY, ORDERED_SEQUENCE},
        subjects=(Subject("egfr", "below", "..."),),
        minimum_observations=2,
        minimum_window_days=90,
    )

A detector that forgets to check any of this still cannot assert it, because
the engine checks the contract rather than trusting the detector.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Directions an abnormality can persist in.
_DIRECTIONS = ("below", "above", "either", "")


class TemporalRequirement(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    """One thing a detector needs to have been shown about time."""

    #: One report, one moment. The default, and all a level-2 pattern may ask.
    SINGLE_REPORT = "SINGLE_REPORT"
    #: The same analyte measured more than once, so a transient abnormality
    #: can be told from a lasting one at all.
    REPEATED_MEASUREMENTS = "REPEATED_MEASUREMENTS"
    #: Those measurements must span a minimum elapsed time. Necessary for a
    #: chronicity criterion and, on its own, nowhere near sufficient.
    TIME_WINDOW = "TIME_WINDOW"
    #: The abnormality itself must have been present at both ends of that
    #: window, in the same direction. This is the one that separates chronic
    #: disease from a long history of normal results and one bad day.
    PERSISTENT_ABNORMALITY = "PERSISTENT_ABNORMALITY"
    #: The observations must carry reliable, distinct dates, so "before" and
    #: "after" mean something. Two results collected the same day cannot show
    #: a direction, whatever their values.
    ORDERED_SEQUENCE = "ORDERED_SEQUENCE"


@dataclass(frozen=True, slots=True)
class Subject:
    """An analyte the temporal requirements apply to, and how."""

    analyte: str
    #: "below" / "above" for a persistence requirement; "either" when any
    #: direction counts; "" when only repetition matters, not abnormality.
    abnormal_direction: str = ""
    why: str = ""

    def __post_init__(self) -> None:
        if not self.analyte:
            raise ValueError("a temporal subject needs an analyte")
        if self.abnormal_direction not in _DIRECTIONS:
            raise ValueError(
                f"{self.analyte}: abnormal_direction is one of {_DIRECTIONS}, "
                f"got {self.abnormal_direction!r}"
            )


@dataclass(frozen=True, slots=True)
class TemporalContract:
    """Everything a detector needs shown about time, in one declarable place."""

    requirements: frozenset[TemporalRequirement] = frozenset(
        {TemporalRequirement.SINGLE_REPORT}
    )
    subjects: tuple[Subject, ...] = ()
    minimum_observations: int = 1
    minimum_window_days: int = 0
    #: "any" - one subject satisfying every requirement is enough (a condition
    #: with alternative entry criteria). "all" - every subject must.
    subject_mode: str = "any"
    #: Why this timeline, in a sentence, so a result can explain what it
    #: wanted rather than only that something was missing.
    rationale: str = ""

    def __post_init__(self) -> None:
        R = TemporalRequirement
        if not self.requirements:
            raise ValueError("a temporal contract declares at least one requirement")
        if self.subject_mode not in ("any", "all"):
            raise ValueError(
                f"subject_mode is 'any' or 'all', got {self.subject_mode!r}"
            )
        if self.single_report_only:
            if self.subjects or self.minimum_window_days or self.minimum_observations > 1:
                raise ValueError(
                    "a SINGLE_REPORT contract cannot also ask for repetition, "
                    "a window or a subject - say what it needs instead"
                )
            return

        if not self.rationale.strip():
            raise ValueError(
                "a contract asking for more than one report must say why, so "
                "the result can name what it wanted when it is not available"
            )
        if not self.subjects:
            raise ValueError(
                "a temporal requirement beyond SINGLE_REPORT applies to "
                "specific analytes; name them in subjects"
            )
        if R.REPEATED_MEASUREMENTS in self.requirements and self.minimum_observations < 2:
            raise ValueError(
                "REPEATED_MEASUREMENTS needs minimum_observations of at least 2"
            )
        if R.TIME_WINDOW in self.requirements and self.minimum_window_days <= 0:
            raise ValueError("TIME_WINDOW needs a minimum_window_days above zero")
        if R.PERSISTENT_ABNORMALITY in self.requirements:
            if R.REPEATED_MEASUREMENTS not in self.requirements:
                raise ValueError(
                    "PERSISTENT_ABNORMALITY means the abnormality was there at "
                    "both ends, which needs REPEATED_MEASUREMENTS too"
                )
            undirected = [s.analyte for s in self.subjects if not s.abnormal_direction]
            if undirected:
                raise ValueError(
                    f"PERSISTENT_ABNORMALITY needs a direction for every "
                    f"subject; {undirected} have none. 'Abnormal' without a "
                    f"direction would let a value that swung from low to high "
                    f"count as having persisted."
                )

    @property
    def single_report_only(self) -> bool:
        return self.requirements == frozenset({TemporalRequirement.SINGLE_REPORT})

    @property
    def analytes(self) -> tuple[str, ...]:
        return tuple(s.analyte for s in self.subjects)

    def describe(self) -> str:
        if self.single_report_only:
            return "One report."
        parts = []
        if TemporalRequirement.REPEATED_MEASUREMENTS in self.requirements:
            parts.append(f"at least {self.minimum_observations} measurements")
        if TemporalRequirement.TIME_WINDOW in self.requirements:
            parts.append(f"spanning at least {self.minimum_window_days} days")
        if TemporalRequirement.PERSISTENT_ABNORMALITY in self.requirements:
            joined = " or ".join(
                f"{s.analyte} {s.abnormal_direction} its range" for s in self.subjects
            )
            parts.append(f"with {joined} at both ends")
        if TemporalRequirement.ORDERED_SEQUENCE in self.requirements:
            parts.append("on distinct, ordered dates")
        return ", ".join(parts) + "."


#: The contract every level-2 pattern has, and the default everywhere else.
SINGLE_REPORT = TemporalContract()


@dataclass(frozen=True, slots=True)
class TemporalGap:
    """One thing the evidence set could not show, in words a result can use."""

    requirement: TemporalRequirement
    analyte: str
    detail: str


def evaluate(contract: TemporalContract, evidence) -> list[TemporalGap]:
    """What the evidence set fails to show for this contract.

    An empty list means every declared requirement is satisfied. This is
    called by the engine for every detector, so a detector that forgets to
    check its own timeline still cannot assert anything it was not shown.
    """
    if contract.single_report_only:
        return []

    per_subject = {
        subject.analyte: _gaps_for(contract, subject, evidence)
        for subject in contract.subjects
    }
    if contract.subject_mode == "all":
        return [gap for gaps in per_subject.values() for gap in gaps]

    # "any": satisfied as soon as one subject has no gaps at all.
    if any(not gaps for gaps in per_subject.values()):
        return []
    # None satisfied - report every subject's gaps so the result can say what
    # would have been enough, rather than naming one arbitrary analyte.
    return [gap for gaps in per_subject.values() for gap in gaps]


def _gaps_for(contract: TemporalContract, subject: Subject, evidence) -> list[TemporalGap]:
    R = TemporalRequirement
    gaps: list[TemporalGap] = []
    series = evidence.series_for(subject.analyte)

    if series is None or series.count < contract.minimum_observations:
        have = 0 if series is None else series.count
        gaps.append(TemporalGap(
            R.REPEATED_MEASUREMENTS, subject.analyte,
            f"{contract.minimum_observations} measurements of "
            f"{subject.analyte} are needed and {have} are available",
        ))
        # Everything below needs the series, so stop here for this subject.
        return gaps

    if R.TIME_WINDOW in contract.requirements and (
        series.span_days < contract.minimum_window_days
    ):
        gaps.append(TemporalGap(
            R.TIME_WINDOW, subject.analyte,
            f"{subject.analyte} results spanning {contract.minimum_window_days} "
            f"days are needed; these span {series.span_days}",
        ))

    if R.ORDERED_SEQUENCE in contract.requirements and not _ordered(series):
        gaps.append(TemporalGap(
            R.ORDERED_SEQUENCE, subject.analyte,
            f"the {subject.analyte} results do not carry distinct dates, so "
            f"which came first cannot be established",
        ))

    if R.PERSISTENT_ABNORMALITY in contract.requirements and not _persisted(
        series, subject.abnormal_direction
    ):
        gaps.append(TemporalGap(
            R.PERSISTENT_ABNORMALITY, subject.analyte,
            f"{subject.analyte} is not {subject.abnormal_direction} its "
            f"reference range at both ends of this window "
            f"({series.persistence.value.lower()}), so the abnormality was "
            f"not shown to be sustained. A long observation window is not the "
            f"same as a sustained abnormality.",
        ))
    return gaps


def _ordered(series) -> bool:
    dates = [o.observed_on for o in series.observations]
    return len(set(dates)) == len(dates)


def _persisted(series, direction: str) -> bool:
    from intelligence.document.contracts import ReferenceStatus

    if direction == "either":
        return series.earliest.abnormal and series.latest.abnormal
    wanted = (
        ReferenceStatus.BELOW if direction == "below" else ReferenceStatus.ABOVE
    )
    return series.abnormal_in_direction(wanted)
