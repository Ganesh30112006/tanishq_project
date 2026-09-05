"""Expected-report-schema engine (spec sections 14, 15).

For a given report type the active :class:`~apps.reports.models.ReportSchema`
defines expected / required / optional fields, accepted units, deterministic
validation rules, expected sections and temporal requirements. The engine
compares extracted data against that schema and returns one of
``COMPLETE / INCOMPLETE / AMBIGUOUS / INVALID / CONFLICTING``.

Schemas are versioned; a report records which schema version it was evaluated
against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from apps.common.enums import CompletenessStatus, ReportClass
from apps.reports.models import ReportSchema


@dataclass(slots=True)
class FieldCheck:
    name: str
    present: bool
    value: Decimal | None = None
    unit: str = ""
    in_range: bool | None = None
    conflicting: bool = False
    note: str = ""


@dataclass(slots=True)
class SchemaComparison:
    schema_version: int
    status: str
    checks: list[FieldCheck] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    @property
    def is_finalizable(self) -> bool:
        return self.status == CompletenessStatus.COMPLETE


def active_schema(report_class: str) -> ReportSchema | None:
    if report_class not in ReportClass.values:
        return None
    return (
        ReportSchema.objects.filter(report_class=report_class, status=ReportSchema.Status.ACTIVE)
        .order_by("-version")
        .first()
    )


class SchemaEngine:
    def compare(
        self,
        *,
        schema: ReportSchema,
        values_by_field: dict[str, list[dict]],
    ) -> SchemaComparison:
        """``values_by_field``: field name -> list of
        ``{"value": Decimal|None, "unit": str, "state": str}`` (normalized).
        Multiple entries for one field are how a same-report conflict shows up.
        """
        definition = schema.definition or {}
        required = list(definition.get("required_fields", []))
        expected = set(required) | set(definition.get("optional_fields", []))
        rules = definition.get("validation_rules", {})

        comparison = SchemaComparison(schema_version=schema.version, status=CompletenessStatus.COMPLETE)

        for field_name in sorted(expected):
            entries = values_by_field.get(field_name, [])
            usable = [e for e in entries if e.get("value") is not None]

            if not usable:
                comparison.checks.append(FieldCheck(field_name, present=False))
                if field_name in required:
                    comparison.missing_required.append(field_name)
                continue

            distinct = {str(e["value"]) for e in usable}
            conflicting = len(distinct) > 1
            entry = usable[0]
            value = entry["value"]
            unit = entry.get("unit", "")

            rule = rules.get(field_name, {})
            in_range: bool | None = None
            lo, hi = rule.get("min"), rule.get("max")
            if lo is not None or hi is not None:
                in_range = (lo is None or value >= Decimal(str(lo))) and (
                    hi is None or value <= Decimal(str(hi))
                )

            check = FieldCheck(
                name=field_name,
                present=True,
                value=value,
                unit=unit,
                in_range=in_range,
                conflicting=conflicting,
            )
            comparison.checks.append(check)

            if conflicting:
                comparison.conflicting.append(field_name)
            if in_range is False:
                comparison.invalid.append(field_name)

        comparison.status = self._classify(comparison)
        return comparison

    @staticmethod
    def _classify(c: SchemaComparison) -> str:
        if c.conflicting:
            return CompletenessStatus.CONFLICTING
        if c.invalid:
            return CompletenessStatus.INVALID
        if c.ambiguous:
            return CompletenessStatus.AMBIGUOUS
        if c.missing_required:
            return CompletenessStatus.INCOMPLETE
        return CompletenessStatus.COMPLETE
