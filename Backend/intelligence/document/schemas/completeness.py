"""Compare an extracted report against its schema.

The outcome precedence, worst first, matches ``apps.reports.schema_engine`` so
the two engines never disagree on a report:

    CONFLICTING  two different values for the same field in one report
    INVALID      a value outside the field's plausibility bounds
    AMBIGUOUS    a value with no usable unit, or a non-numeric value
    INCOMPLETE   a required field is absent
    COMPLETE     every required field present, in range, unambiguous
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.document.contracts import CompletenessOutcome
from intelligence.document.schemas.model import ReportSchema


@dataclass(frozen=True, slots=True)
class ExtractedValue:
    #: The label as it appeared in the document (an alias is fine).
    label: str
    value: float | None
    unit: str = ""
    #: Free-text carried through for the ambiguity note when value is None.
    raw: str = ""


@dataclass(slots=True)
class FieldOutcome:
    name: str
    present: bool
    value: float | None = None
    unit: str = ""
    unit_accepted: bool | None = None
    in_range: bool | None = None
    conflicting: bool = False
    ambiguous: bool = False
    note: str = ""


@dataclass(slots=True)
class CompletenessReport:
    outcome: CompletenessOutcome
    schema_version: int
    fields: list[FieldOutcome] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    unrecognised_labels: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.outcome is CompletenessOutcome.COMPLETE


def assess_completeness(
    schema: ReportSchema, values: list[ExtractedValue]
) -> CompletenessReport:
    report = CompletenessReport(
        outcome=CompletenessOutcome.COMPLETE, schema_version=schema.version
    )

    grouped: dict[str, list[ExtractedValue]] = {}
    for extracted in values:
        canonical = schema.canonical_for(extracted.label)
        if canonical is None:
            report.unrecognised_labels.append(extracted.label)
            continue
        grouped.setdefault(canonical, []).append(extracted)

    for spec in schema.fields:
        entries = grouped.get(spec.name, [])
        numeric = [e for e in entries if e.value is not None]
        outcome = FieldOutcome(name=spec.name, present=bool(entries))

        if not entries:
            if spec.required:
                report.missing_required.append(spec.name)
            report.fields.append(outcome)
            continue

        if not numeric:
            outcome.ambiguous = True
            outcome.note = "value present but not a number"
            report.ambiguous.append(spec.name)
            report.fields.append(outcome)
            continue

        distinct = {round(e.value, 6) for e in numeric}
        if len(distinct) > 1:
            outcome.conflicting = True
            outcome.note = f"{sorted(distinct)} reported for the same field"
            report.conflicting.append(spec.name)
            report.fields.append(outcome)
            continue

        entry = numeric[0]
        outcome.value = entry.value
        outcome.unit = entry.unit

        if spec.accepted_units:
            outcome.unit_accepted = entry.unit in spec.accepted_units
            if not entry.unit:
                outcome.ambiguous = True
                outcome.note = "no unit given"
                report.ambiguous.append(spec.name)
                report.fields.append(outcome)
                continue
            if not outcome.unit_accepted:
                outcome.ambiguous = True
                outcome.note = (
                    f"unit {entry.unit!r} not in {spec.accepted_units}"
                )
                report.ambiguous.append(spec.name)
                report.fields.append(outcome)
                continue

        lo, hi = spec.min_value, spec.max_value
        if lo is not None or hi is not None:
            outcome.in_range = (lo is None or entry.value >= lo) and (
                hi is None or entry.value <= hi
            )
            if outcome.in_range is False:
                outcome.note = f"{entry.value} outside plausibility bounds [{lo}, {hi}]"
                report.invalid.append(spec.name)

        report.fields.append(outcome)

    report.outcome = _classify(report)
    return report


def _classify(report: CompletenessReport) -> CompletenessOutcome:
    if report.conflicting:
        return CompletenessOutcome.CONFLICTING
    if report.invalid:
        return CompletenessOutcome.INVALID
    if report.ambiguous:
        return CompletenessOutcome.AMBIGUOUS
    if report.missing_required:
        return CompletenessOutcome.INCOMPLETE
    return CompletenessOutcome.COMPLETE
