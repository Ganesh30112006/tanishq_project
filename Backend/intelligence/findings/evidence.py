"""What a detector is allowed to look at, and where each item came from.

Two rules are enforced here rather than left to each detector:

**Only values that passed validation become evidence.** Exactly one
``ValueStatus`` - ``OBSERVED`` - persists a clinical value; a value the
document stage marked ambiguous, conflicting, invalid, unreadable or in need
of review is not evidence of anything. If detectors were free to read the raw
list, one of them would eventually build a finding on a number nobody trusted.

**The laboratory's printed reference range wins.** It was set for that assay on
that instrument; the fallback table is a textbook average. When the fallback is
used the measurement says so, and every finding built on it inherits the
caveat.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from intelligence.document.contracts import ReferenceStatus
from intelligence.document.provenance.record import Provenance
from intelligence.document.validation.checks import ValidatedValue
from intelligence.findings.contracts import EvidenceRef, EvidenceRequirement, Finding
from intelligence.knowledge import reference_ranges as RR


@dataclass(frozen=True, slots=True)
class Measurement:
    analyte: str
    #: The value and unit the reference comparison was actually made in.
    value: float
    unit: str
    reference_low: float | None
    reference_high: float | None
    reference_text: str
    #: "report" | "fallback-table" | "none"
    reference_source: str
    reference_kind: str          # "reference_interval" | "decision_threshold" | ""
    status: ReferenceStatus
    reference_note: str = ""
    raw_value: float | None = None
    raw_unit: str = ""
    #: The same measurement in this analyte's canonical unit, when it could be
    #: converted. The reference comparison above is deliberately done in the
    #: laboratory's own units - that is what its printed range is expressed in
    #: - but a trend across laboratories has to be in one unit, and this is it.
    canonical_value: float | None = None
    canonical_unit: str = ""
    provenance: Provenance | None = None

    @property
    def is_high(self) -> bool:
        return self.status is ReferenceStatus.ABOVE

    @property
    def is_low(self) -> bool:
        return self.status is ReferenceStatus.BELOW

    @property
    def comparable(self) -> bool:
        return self.status is not ReferenceStatus.UNKNOWN

    def to_ref(self) -> EvidenceRef:
        prov = self.provenance
        return EvidenceRef(
            key=self.analyte, kind="measurement", value=self.value, unit=self.unit,
            reference_text=self.reference_text,
            reference_source=self.reference_source,
            reference_status=self.status.value,
            page=prov.page if prov else None,
            section=prov.section if prov else "",
            source_text=prov.source_text if prov else "",
            char_span=prov.char_span if prov else None,
            text_source=prov.text_source.value if prov else "",
            ocr_provider=prov.ocr_provider if prov else "",
        )


@dataclass(slots=True)
class EvidenceSet:
    measurements: dict[str, Measurement] = field(default_factory=dict)
    #: Findings already derived at a lower level, so level 3 can build on level 2.
    findings: dict[str, Finding] = field(default_factory=dict)
    sex: str | None = None
    age_years: float | None = None
    #: Analytes that appeared on the report but did not survive validation.
    unusable: list[str] = field(default_factory=list)
    range_table_version: str = RR.RANGE_TABLE_VERSION
    #: Days between the earliest and latest observation in the set, when more
    #: than one report is behind it.
    observation_window_days: float | None = None
    #: analyte -> the same analyte across time, when a history was assembled.
    #: Empty for the single-report case, which is what the document pipeline
    #: produces. See ``intelligence.findings.history``.
    series: dict = field(default_factory=dict)

    def measurement(self, analyte: str) -> Measurement | None:
        return self.measurements.get(analyte)

    def unmet_temporal_requirements(self, contract) -> list:
        """What this set fails to show for a detector's temporal contract.

        Derived from the series actually present, never declared. A set cannot
        claim a timeline it does not hold, because there is nowhere to write
        the claim.
        """
        from intelligence.findings import temporal

        return temporal.evaluate(contract, self)

    def series_for(self, analyte: str):
        """The analyte across time, or ``None`` when only one report is here."""
        return self.series.get(analyte)

    def finding(self, code: str) -> Finding | None:
        return self.findings.get(code)

    def has(self, requirement: EvidenceRequirement) -> bool:
        if requirement.is_finding:
            return requirement.key in self.findings
        return requirement.key in self.measurements

    def missing(self, requirements: Iterable[EvidenceRequirement]) -> list[str]:
        return [r.key for r in requirements if not self.has(r)]

    def add_finding(self, finding: Finding) -> None:
        self.findings[finding.code] = finding

    def ref_for(self, code: str) -> EvidenceRef | None:
        found = self.findings.get(code)
        if found is None:
            return None
        return EvidenceRef(key=code, kind="finding")


def _resolve_reference(value: ValidatedValue, sex: str | None):
    """(low, high, text, source, kind, note, compare_value, compare_unit)."""
    canonical = value.normalized
    canonical_ok = canonical is not None and canonical.convertible

    # 1. The laboratory's own printed range, compared in the printed units.
    if value.reference.is_numeric and value.value is not None:
        return (
            value.reference.low, value.reference.high, value.reference.text,
            "report", "reference_interval", "", value.value, value.unit,
        )

    # 2. The fallback table, compared in canonical units.
    if canonical_ok and value.analyte:
        interval = RR.lookup(value.analyte, sex=sex)
        if interval is not None and interval.unit == canonical.unit:
            return (
                interval.low, interval.high, interval.describe(),
                "fallback-table", interval.kind, interval.note,
                canonical.value, canonical.unit,
            )

    compare_value = canonical.value if canonical_ok else value.value
    compare_unit = canonical.unit if canonical_ok else value.unit
    return (None, None, "", "none", "", "", compare_value, compare_unit)


def _status(value: float | None, low: float | None, high: float | None) -> ReferenceStatus:
    if value is None or (low is None and high is None):
        return ReferenceStatus.UNKNOWN
    if low is not None and value < low:
        return ReferenceStatus.BELOW
    if high is not None and value > high:
        return ReferenceStatus.ABOVE
    return ReferenceStatus.WITHIN


def build_evidence(
    records: Iterable,
    *,
    sex: str | None = None,
    age_years: float | None = None,
) -> EvidenceSet:
    """Build an EvidenceSet from the document pipeline's extracted records.

    ``records`` is any iterable of objects with ``.value`` (a ValidatedValue)
    and ``.provenance`` - i.e. the pipeline's ``ExtractedValueRecord``.
    """
    evidence = EvidenceSet(sex=sex, age_years=age_years)

    for record in records:
        value: ValidatedValue = record.value
        provenance = getattr(record, "provenance", None)

        if not value.status.persists_clinical_value or not value.analyte:
            if value.analyte:
                evidence.unusable.append(value.analyte)
            continue

        canonical = value.normalized
        low, high, text, source, kind, note, cmp_value, cmp_unit = _resolve_reference(
            value, sex
        )
        if cmp_value is None:
            evidence.unusable.append(value.analyte)
            continue

        evidence.measurements[value.analyte] = Measurement(
            analyte=value.analyte,
            value=cmp_value,
            unit=cmp_unit,
            reference_low=low,
            reference_high=high,
            reference_text=text,
            reference_source=source,
            reference_kind=kind,
            reference_note=note,
            status=_status(cmp_value, low, high),
            raw_value=value.value,
            raw_unit=value.unit,
            canonical_value=(
                canonical.value if canonical and canonical.convertible else None
            ),
            canonical_unit=(
                canonical.unit if canonical and canonical.convertible else ""
            ),
            provenance=provenance,
        )
    return evidence
