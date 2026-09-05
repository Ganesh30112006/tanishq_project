"""Minimized, patient-scoped context assembly for the AI assistant (spec section 37).

Django has already authenticated the user, checked RBAC, resolved the patient
from what the user is allowed to see, and run the resource-level
authorization check. This module then assembles the *minimum necessary*
context - never the whole record - and labels every value with its clinical
data state so the assistant can keep OBSERVED data separate from everything
else. Free-text clinical notes are only included for a document-assist request
about a specific report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from decimal import Decimal, InvalidOperation

from apps.ai.models import AiInteraction, AiKnowledgeDocument
from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES, ValidationStatus

MAX_BLOCKS = 30
MAX_KNOWLEDGE_DOCS = 10
KNOWLEDGE_BODY_CHARS = 800


@dataclass(slots=True)
class AssembledContext:
    blocks: list[dict] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    knowledge: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.blocks and not self.knowledge


class ContextAssembler:
    def assemble(self, *, patient, kind: str, report=None) -> AssembledContext:
        ctx = AssembledContext()

        if kind in (AiInteraction.Kind.REPORT_SUMMARY, AiInteraction.Kind.DOC_ASSIST):
            self._add_report(ctx, report)
        else:
            self._add_latest_labs(ctx, patient)
            self._add_latest_measurements(ctx, patient)
            self._add_active_conditions(ctx, patient)
            self._add_active_medications(ctx, patient)

        ctx.blocks = ctx.blocks[:MAX_BLOCKS]
        ctx.refs = [b["ref"] for b in ctx.blocks]
        ctx.knowledge = self._approved_knowledge()
        return ctx

    # -- patient-scoped sources ------------------------------------
    def _add_report(self, ctx: AssembledContext, report) -> None:
        if report is None:
            return
        for t in report.tests.filter(validation_status=ValidationStatus.PASSED):
            value = t.value_normalized if t.value_normalized is not None else t.value_raw
            ctx.blocks.append(
                {
                    "ref": f"reporttest:{t.public_id}",
                    "type": "report_test",
                    "label": t.name,
                    "content": f"{_num(value) if not isinstance(value, str) else value} {t.unit_normalized or t.unit_raw}".strip(),
                    "state": t.state,
                    "observed_at": _iso(report.collected_at),
                }
            )
        for finding in report.findings.all()[:5]:
            ctx.blocks.append(
                {
                    "ref": f"reportfinding:{finding.public_id}",
                    "type": "report_finding",
                    "label": finding.category,
                    "content": finding.text[:400],
                    "state": "DERIVED",
                    "observed_at": _iso(report.reported_at),
                }
            )

    def _add_latest_labs(self, ctx: AssembledContext, patient) -> None:
        from apps.laboratories.models import LabResult

        seen: set[str] = set()
        rows = (
            LabResult.objects.filter(
                order__patient=patient,
                state__in=TRUSTWORTHY_CLINICAL_STATES,
                superseded_by__isnull=True,
            )
            .order_by("-observed_at", "-recorded_at")
        )
        for lr in rows:
            if lr.analyte in seen:
                continue
            seen.add(lr.analyte)
            value = lr.value_normalized if lr.value_normalized is not None else lr.value_raw
            ctx.blocks.append(
                {
                    "ref": f"labresult:{lr.public_id}",
                    "type": "lab_result",
                    "label": lr.analyte,
                    "content": f"{_num(value)} {lr.unit_normalized or lr.unit_raw}".strip(),
                    "state": lr.state,
                    "observed_at": _iso(lr.observed_at or lr.reported_at),
                }
            )

    def _add_latest_measurements(self, ctx: AssembledContext, patient) -> None:
        from apps.health.models import HealthMeasurement

        seen: set[str] = set()
        for m in HealthMeasurement.objects.filter(
            patient=patient, state__in=TRUSTWORTHY_CLINICAL_STATES
        ).order_by("-observed_at"):
            if m.kind in seen:
                continue
            seen.add(m.kind)
            ctx.blocks.append(
                {
                    "ref": f"measurement:{m.public_id}",
                    "type": "measurement",
                    "label": m.get_kind_display(),
                    "content": f"{_num(m.value_num)} {m.unit}".strip(),
                    "state": m.state,
                    "observed_at": _iso(m.observed_at),
                }
            )

    def _add_active_conditions(self, ctx: AssembledContext, patient) -> None:
        from apps.medical_records.models import Condition

        for c in patient.conditions.exclude(clinical_status=Condition.ClinicalStatus.RESOLVED)[:10]:
            ctx.blocks.append(
                {
                    "ref": f"condition:{c.public_id}",
                    "type": "condition",
                    "label": c.label,
                    "content": f"status {c.get_clinical_status_display()}",
                    "state": "OBSERVED",
                    "observed_at": _iso(c.onset_date),
                }
            )

    def _add_active_medications(self, ctx: AssembledContext, patient) -> None:
        from apps.medical_records.models import Medication

        for med in patient.medications.filter(status=Medication.Status.ACTIVE)[:10]:
            ctx.blocks.append(
                {
                    "ref": f"medication:{med.public_id}",
                    "type": "medication",
                    "label": med.name,
                    "content": " ".join(x for x in (med.dose, med.route, med.frequency) if x),
                    "state": "OBSERVED",
                    "observed_at": None,
                }
            )

    # -- approved general knowledge (not patient data) --------------
    def _approved_knowledge(self) -> list[dict]:
        return [
            {"title": d.title, "body": d.body[:KNOWLEDGE_BODY_CHARS]}
            for d in AiKnowledgeDocument.objects.filter(is_approved=True).order_by("title")[
                :MAX_KNOWLEDGE_DOCS
            ]
        ]


def _iso(value) -> str | None:
    """Render an observation time for a human reader.

    The assistant's output is shown verbatim to a clinician, so a full
    microsecond ISO timestamp ("2026-09-03T18:20:43.331591+00:00") is noise
    that buries the clinically relevant part - the date. Sorting and model
    input never read this field; it is display context only.
    """
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y") if not hasattr(value, "hour") else value.strftime("%d %b %Y, %H:%M")
    return str(value)


def _num(value) -> str:
    """Render a numeric value without database padding zeros."""
    if value is None:
        return ""
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)
