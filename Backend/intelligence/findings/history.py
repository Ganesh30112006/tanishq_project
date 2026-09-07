"""The same analyte across time, and what a sequence is allowed to say.

    eGFR  92 -> 84 -> 71 -> 63

is a different thing from

    eGFR  92 -> 63 -> 94

and a system that reported only the latest value, or only the worst, would
describe both the same way. The first is a decline. The second is one odd
result between two normal ones, which is far more often a sample taken while
the patient was dehydrated than the beginning of anything.

What this module produces is **trend evidence**, and that distinction is the
whole design. A `Series` says what the numbers did: falling, rising, stable,
fluctuating; the abnormality persisted, or it came back to normal. It never
says what caused it and never names a disease. Turning persistence into a
condition is a level-3 detector's job, done under an evidence contract, with a
hedged name and human review - and only for the conditions whose definition
actually contains a length of time.

Three rules do most of the work:

**No move counts until it exceeds ordinary variation.** Every laboratory value
wobbles between samples without the patient changing. The per-analyte
thresholds live in ``intelligence.knowledge.variation`` and a trend that used
them says so.

**Two points are not a trend.** They are a comparison, and are reported as
one. A direction needs at least three.

**Units and reference ranges must be comparable.** The trend is plotted in the
canonical unit, so two laboratories reporting haemoglobin in g/dL and g/L form
one series - while the reference *status* still comes from each laboratory's
own printed range, in its own units. Those answer different questions and are
computed separately. Values that cannot be brought to a common scale are not
put in a series at all, and the analyte is named in ``unusable_series`` rather
than quietly going missing. When the printed range changed between reports the
series carries that as a caveat, because "was abnormal, now normal" may mean
the range moved rather than the patient.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from intelligence.document.contracts import ReferenceStatus
from intelligence.findings.contracts import EvidenceTemporality
from intelligence.findings.evidence import EvidenceSet, Measurement, build_evidence
from intelligence.knowledge import variation as VAR

#: A direction needs at least this many observations. Two points are a
#: comparison; three is the fewest that can distinguish a move from a wobble.
MIN_OBSERVATIONS_FOR_A_DIRECTION = 3


class Trend(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    RISING = "RISING"
    FALLING = "FALLING"
    #: Moved, but not consistently in one direction.
    FLUCTUATING = "FLUCTUATING"
    #: No move larger than ordinary variation between samples.
    STABLE = "STABLE"
    #: Fewer than three observations, or no comparable values.
    INSUFFICIENT = "INSUFFICIENT"


class Persistence(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    #: Outside the range in the same direction at the start and at the end.
    PERSISTENT = "PERSISTENT"
    #: Was outside the range at some point and is inside it now.
    TRANSIENT = "TRANSIENT"
    #: Inside the range throughout.
    NEVER_ABNORMAL = "NEVER_ABNORMAL"
    #: Inside the range earlier and outside it now.
    NEW = "NEW"
    #: Not enough comparable observations to say.
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


@dataclass(frozen=True, slots=True)
class Observation:
    """One measurement of one analyte, on one date, from one report."""

    analyte: str
    value: float
    unit: str
    observed_on: date
    status: ReferenceStatus
    report_id: str
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str = ""
    reference_source: str = ""

    @property
    def abnormal(self) -> bool:
        return self.status in (ReferenceStatus.ABOVE, ReferenceStatus.BELOW)


@dataclass(frozen=True, slots=True)
class Series:
    """One analyte over time, and what the sequence supports saying."""

    analyte: str
    unit: str
    observations: tuple[Observation, ...]
    trend: Trend
    persistence: Persistence
    #: Days between the first and last observation.
    span_days: int
    caveats: tuple[str, ...] = ()
    variation_table_version: str = VAR.VARIATION_TABLE_VERSION

    @property
    def latest(self) -> Observation:
        return self.observations[-1]

    @property
    def earliest(self) -> Observation:
        return self.observations[0]

    @property
    def count(self) -> int:
        return len(self.observations)

    def abnormal_in_direction(self, direction: ReferenceStatus) -> bool:
        """Was it outside the range this way on both the first and the last?

        The question a chronicity criterion actually asks. Being abnormal at
        some point in between is not the same claim.
        """
        return (
            self.earliest.status is direction and self.latest.status is direction
        )

    def describe(self) -> str:
        first, last = self.earliest, self.latest
        return (
            f"{self.analyte}: {first.value} -> {last.value} {self.unit} over "
            f"{self.span_days} days ({self.count} results), "
            f"{self.trend.value.lower()}, {self.persistence.value.lower()}"
        )


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    """One report's validated values, with the date the sample was taken."""

    report_id: str
    observed_on: date
    #: The document pipeline's ExtractedValueRecord objects.
    records: Sequence


def _classify_trend(analyte: str, observations: Sequence[Observation]) -> Trend:
    if len(observations) < MIN_OBSERVATIONS_FOR_A_DIRECTION:
        return Trend.INSUFFICIENT

    moves: list[int] = []
    for earlier, later in zip(observations, observations[1:], strict=False):
        if not VAR.is_significant(analyte, earlier.value, later.value):
            continue
        moves.append(1 if later.value > earlier.value else -1)

    if not moves:
        return Trend.STABLE
    if all(m == 1 for m in moves):
        return Trend.RISING
    if all(m == -1 for m in moves):
        return Trend.FALLING
    return Trend.FLUCTUATING


def _classify_persistence(observations: Sequence[Observation]) -> Persistence:
    comparable = [o for o in observations if o.status is not ReferenceStatus.UNKNOWN]
    if len(comparable) < 2:
        return Persistence.NOT_ESTABLISHED

    first, last = comparable[0], comparable[-1]
    if not any(o.abnormal for o in comparable):
        return Persistence.NEVER_ABNORMAL
    if first.abnormal and last.abnormal and first.status is last.status:
        return Persistence.PERSISTENT
    if last.abnormal and not first.abnormal:
        return Persistence.NEW
    if first.abnormal and not last.abnormal:
        return Persistence.TRANSIENT
    # Abnormal at both ends but in opposite directions: a real thing, and not
    # something either word above describes.
    return Persistence.NOT_ESTABLISHED


def _caveats(analyte: str, observations: Sequence[Observation]) -> tuple[str, ...]:
    notes: list[str] = []

    method = VAR.method_caveat(analyte)
    if method:
        notes.append(method)

    ranges = {
        (o.reference_low, o.reference_high)
        for o in observations
        if o.status is not ReferenceStatus.UNKNOWN
    }
    if len(ranges) > 1:
        notes.append(
            "The reference range printed against this test changed between "
            "reports, so a move from 'abnormal' to 'normal' may be the range "
            "moving rather than the patient."
        )

    sources = {o.reference_source for o in observations if o.reference_source}
    if "fallback-table" in sources:
        notes.append(
            "At least one of these results carried no printed reference range "
            "and was compared against a general adult range."
        )

    uncompared = sum(1 for o in observations if o.status is ReferenceStatus.UNKNOWN)
    if uncompared:
        notes.append(
            f"{uncompared} of {len(observations)} results had no range to be "
            f"compared against and do not contribute to whether the "
            f"abnormality persisted."
        )

    notes.append(
        f"A change is only called a change when it exceeds "
        f"{VAR.significant_fraction(analyte):.0%}, which is roughly the "
        f"variation expected between samples from an unchanged patient."
    )
    return tuple(notes)


def build_series(analyte: str, observations: Iterable[Observation]) -> Series | None:
    """One analyte's observations, ordered, classified and caveated."""
    ordered = sorted(observations, key=lambda o: o.observed_on)
    if not ordered:
        return None

    units = {o.unit for o in ordered}
    if len(units) > 1:
        # Values that are not in the same unit are not one series. Observations
        # carry the canonical unit wherever the analyte has a conversion rule,
        # so reaching here means an analyte with no rule was reported in two
        # different units - and silently plotting those together would be the
        # worst possible failure in this module. The caller records the drop.
        return None

    return Series(
        analyte=analyte,
        unit=ordered[0].unit,
        observations=tuple(ordered),
        trend=_classify_trend(analyte, ordered),
        persistence=_classify_persistence(ordered),
        span_days=(ordered[-1].observed_on - ordered[0].observed_on).days,
        caveats=_caveats(analyte, ordered),
    )


def _observations(snapshot: ReportSnapshot, sex: str | None) -> list[Observation]:
    """Reuse the single-report assembly, so the same validation rules apply."""
    evidence = build_evidence(snapshot.records, sex=sex)
    return [
        _observation(measurement, snapshot)
        for measurement in evidence.measurements.values()
    ]


def _observation(measurement: Measurement, snapshot: ReportSnapshot) -> Observation:
    # The trend is plotted in the canonical unit, not the unit the laboratory
    # printed. Two laboratories reporting haemoglobin in g/dL and g/L are
    # measuring the same thing, and a series that refused to put them together
    # would silently lose the history rather than report it.
    #
    # The reference *status* still comes from the comparison the laboratory's
    # own printed range supports, in its own units. Comparing in one unit and
    # trending in another is correct: they answer different questions.
    value = (
        measurement.canonical_value
        if measurement.canonical_value is not None
        else measurement.value
    )
    unit = measurement.canonical_unit or measurement.unit
    return Observation(
        analyte=measurement.analyte,
        value=value,
        unit=unit,
        observed_on=snapshot.observed_on,
        status=measurement.status,
        report_id=snapshot.report_id,
        reference_low=measurement.reference_low,
        reference_high=measurement.reference_high,
        reference_text=measurement.reference_text,
        reference_source=measurement.reference_source,
    )


@dataclass(slots=True)
class History:
    """The evidence set for the latest report, plus what came before it."""

    evidence: EvidenceSet
    series: dict[str, Series] = field(default_factory=dict)
    reports: int = 0
    span_days: int = 0
    #: Analytes seen across the reports for which no series could be built,
    #: with the reason. A history that is quietly missing an analyte is worse
    #: than one that says which analyte it is missing.
    unusable_series: dict[str, str] = field(default_factory=dict)

    def series_for(self, analyte: str) -> Series | None:
        return self.series.get(analyte)


def build_history(
    snapshots: Sequence[ReportSnapshot],
    *,
    sex: str | None = None,
    age_years: float | None = None,
) -> History:
    """Assemble an evidence set that knows what came before.

    The *latest* snapshot supplies the measurements, so every existing
    single-report detector behaves exactly as it did. What is added is the
    series, and the declaration - on the evidence set - of how much timeline is
    actually behind it. A detector that needs history can then be given it;
    one that does not is unaffected.
    """
    if not snapshots:
        return History(evidence=EvidenceSet(sex=sex, age_years=age_years))

    ordered = sorted(snapshots, key=lambda s: s.observed_on)
    latest = ordered[-1]

    evidence = build_evidence(latest.records, sex=sex, age_years=age_years)

    by_analyte: dict[str, list[Observation]] = {}
    for snapshot in ordered:
        for observation in _observations(snapshot, sex):
            by_analyte.setdefault(observation.analyte, []).append(observation)

    series: dict[str, Series] = {}
    unusable: dict[str, str] = {}
    for analyte, observations in by_analyte.items():
        built = build_series(analyte, observations)
        if built is not None:
            series[analyte] = built
        else:
            unusable[analyte] = (
                "reported in units that cannot be brought to a common scale: "
                + ", ".join(sorted({o.unit for o in observations}))
            )

    span = (ordered[-1].observed_on - ordered[0].observed_on).days
    evidence.series = series
    evidence.observation_window_days = float(span)
    evidence.available_temporality = _temporality(series, len(ordered), span)

    return History(
        evidence=evidence, series=series, reports=len(ordered), span_days=span,
        unusable_series=unusable,
    )


def _temporality(
    series: dict[str, Series], reports: int, span_days: int
) -> frozenset[EvidenceTemporality]:
    """What this set actually holds. Never what a detector wishes it held."""
    available = {EvidenceTemporality.SINGLE_REPORT}
    repeated = any(s.count >= 2 for s in series.values())
    if repeated:
        available.add(EvidenceTemporality.REPEATED_MEASUREMENT)
    if repeated and span_days > 0:
        available.add(EvidenceTemporality.HISTORICAL)
    if reports > 1:
        available.add(EvidenceTemporality.CROSS_REPORT)
    return frozenset(available)
