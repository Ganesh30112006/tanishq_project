"""Presentation shape for a patient AI summary (spec sections 36-38, 42).

Wraps :class:`~apps.ai.services.AiAssistantService` with the fixed question
"Summarize this patient's current authorized clinical picture" and renders
its :class:`~apps.ai.models.AiInteraction` into a display shape. Highlights
are counted directly from the context references the service actually used -
never invented, never a diagnosis (spec sections 35, 38).
"""
from __future__ import annotations

from collections import Counter

from apps.ai.models import AiInteraction
from apps.ai.services import AiAssistantService

DISCLAIMER = (
    "This summary is written by AI. It only repeats the clinical information "
    "already on file that you are allowed to see. It is not a diagnosis, it "
    "does not say what caused what, and it does not replace a doctor's judgement."
)

_REF_LABELS = {
    "labresult": "laboratory result(s)",
    "measurement": "vital-sign measurement(s)",
    "condition": "active condition(s)",
    "medication": "active medication(s)",
    "reporttest": "report test value(s)",
    "reportfinding": "report finding(s)",
}


def _highlights(context_refs: list[str]) -> list[str]:
    kinds = Counter(ref.split(":", 1)[0] for ref in context_refs if ":" in ref)
    return [f"{count} {_REF_LABELS.get(kind, kind)}" for kind, count in kinds.items()]


def build_patient_summary(*, actor, patient, correlation_id: str = "") -> dict:
    """Runs a fresh, audited AI summary and returns the display shape, or
    ``None`` when no authorized context was available (a safe non-answer)."""
    outcome = AiAssistantService().answer(
        actor=actor,
        patient=patient,
        kind=AiInteraction.Kind.HISTORY_SUMMARY,
        question="Summarize this patient's current authorized clinical picture.",
        correlation_id=correlation_id,
    )
    interaction = outcome.value
    if interaction is None:
        return None

    refs = interaction.context_refs or []
    return {
        "summary": interaction.output_text,
        "generated_at": interaction.created_at,
        "context": (
            f"Generated from {len(refs)} authorized record item(s)."
            if refs
            else "There was no clinical information available to summarise."
        ),
        "disclaimer": DISCLAIMER,
        "highlights": _highlights(refs),
        "ok": outcome.ok,
    }
