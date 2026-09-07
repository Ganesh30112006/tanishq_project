"""The shape of a report schema."""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.document.contracts import ReportType


@dataclass(frozen=True, slots=True)
class ReportFieldSpec:
    #: Canonical field name, e.g. "hemoglobin".
    name: str
    required: bool
    #: Other names the same field appears under, lower-cased.
    aliases: tuple[str, ...] = ()
    #: Units accepted on input, before normalisation.
    accepted_units: tuple[str, ...] = ()
    #: The unit the plausibility bounds below are expressed in.
    canonical_unit: str = ""
    #: Wide plausibility bounds in ``canonical_unit`` - not a clinical
    #: reference range. A value outside these is a read error, not a sick
    #: patient.
    min_value: float | None = None
    max_value: float | None = None

    def matches(self, label: str) -> bool:
        label = label.strip().lower()
        return label == self.name.lower() or label in self.aliases


@dataclass(frozen=True, slots=True)
class ReportSchema:
    report_type: ReportType
    version: int
    fields: tuple[ReportFieldSpec, ...]
    expected_sections: tuple[str, ...] = ()
    #: Groups where at least one member must be present. Used where a report
    #: is defined by a family of fields rather than one named field - a
    #: glucose report carries a fasting *or* a random *or* an unqualified
    #: value, and demanding all three would make every real one INCOMPLETE.
    required_any: tuple[tuple[str, ...], ...] = ()
    notes: str = ""
    _by_name: dict[str, ReportFieldSpec] = field(
        default_factory=dict, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        mapping = {spec.name.lower(): spec for spec in self.fields}
        object.__setattr__(self, "_by_name", mapping)
        for group in self.required_any:
            unknown = [name for name in group if name.lower() not in mapping]
            if unknown:
                raise ValueError(
                    f"{self.report_type.value}: required_any names fields the "
                    f"schema does not define: {unknown}"
                )

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.fields if spec.required)

    def canonical_for(self, label: str) -> str | None:
        """Resolve an extracted label to a canonical field name, or ``None``."""
        for spec in self.fields:
            if spec.matches(label):
                return spec.name
        return None

    def spec(self, name: str) -> ReportFieldSpec | None:
        return self._by_name.get(name.lower())
