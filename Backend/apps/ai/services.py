"""AI assistant orchestration (spec sections 36-38).

Flow (the caller has already authenticated, checked RBAC, resolved the patient
from the user's visible set, and run the resource-level authorization check):

1. assemble a minimized, patient-scoped context (never the whole record);
2. if there is nothing to work with, record a BLOCKED interaction and return a
   safe non-answer - the assistant never invents missing medical facts;
3. call the FastAPI AI service with the minimized context + approved knowledge
   + correlation id (no database identifiers it could resolve itself);
4. validate the output, tag it, and record an ``AiInteraction``. The output is
   NEVER written to a clinical record and never becomes trusted data.
"""
from __future__ import annotations

from django.db import transaction

from apps.ai.context import ContextAssembler
from apps.ai.models import AiInteraction
from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.intelligence import AiAnswerResult, IntelligenceClient
from apps.common.services import BaseService, ServiceResult

# Words that, if they appear in AI output, indicate an interpretive/diagnostic
# claim this assistant must not make on its own.
_DISALLOWED_PHRASES = (
    "you have",
    "diagnosis is",
    "i diagnose",
    "you should take",
    "start taking",
    "stop taking",
)


class AiAssistantService(BaseService):
    def __init__(self, *, client: IntelligenceClient | None = None) -> None:
        self.client = client or IntelligenceClient()
        self.assembler = ContextAssembler()

    def answer(
        self,
        *,
        actor,
        patient,
        kind: str,
        question: str,
        report=None,
        correlation_id: str = "",
    ) -> ServiceResult[AiInteraction]:
        # Deliberately not wrapped in one transaction: the outbound call to
        # the intelligence service below is a network round-trip, and a
        # database transaction must never be held open across one (it ties
        # up a connection - and, under SQLite specifically, a write lock -
        # for however long that call takes). Only the final write in
        # ``_record`` needs atomicity.
        context = self.assembler.assemble(patient=patient, kind=kind, report=report)

        # No authorized *patient* context -> safe non-answer. Approved general
        # knowledge alone is not used to answer a patient-specific question.
        if not context.blocks:
            interaction = self._record(
                actor=actor, patient=patient, kind=kind, question=question,
                status=AiInteraction.Status.BLOCKED,
                output_text="No permitted context was available, so no answer was generated.",
                context_refs=[], flags={"missing_information": True, "invented_facts": False},
                correlation_id=correlation_id,
            )
            return ServiceResult.blocked(
                "INSUFFICIENT_DATA",
                "There is no information available that we are allowed to use to answer this.",
                value=interaction,
            )

        result: AiAnswerResult = self.client.ai_answer(
            kind=kind,
            question=question,
            context_blocks=context.blocks,
            knowledge=context.knowledge,
            correlation_id=correlation_id,
        )

        flags = dict(result.flags)
        flags["invented_facts"] = self._contains_disallowed(result.answer)
        flags["used_llm"] = bool(result.flags.get("used_llm", False))

        if flags["invented_facts"] or result.status not in ("OK", "INSUFFICIENT_CONTEXT"):
            interaction = self._record(
                actor=actor, patient=patient, kind=kind, question=question,
                status=AiInteraction.Status.BLOCKED,
                output_text="AI output failed validation and was withheld.",
                context_refs=context.refs, flags=flags, correlation_id=correlation_id,
            )
            return ServiceResult.blocked(
                "REVIEW_REQUIRED", "AI output failed validation.", value=interaction
            )

        status = (
            AiInteraction.Status.COMPLETED
            if result.status == "OK"
            else AiInteraction.Status.BLOCKED
        )
        interaction = self._record(
            actor=actor, patient=patient, kind=kind, question=question,
            status=status, output_text=result.answer,
            context_refs=result.context_refs_used or context.refs,
            flags=flags, correlation_id=correlation_id,
            model_name="deterministic-extractive-summarizer",
        )
        if status == AiInteraction.Status.BLOCKED:
            return ServiceResult.blocked(
                "INSUFFICIENT_DATA",
                "The information available was not enough to answer this.",
                value=interaction,
            )
        return ServiceResult.success(interaction)

    # ------------------------------------------------------------------
    @transaction.atomic
    def _record(
        self, *, actor, patient, kind, question, status, output_text, context_refs, flags,
        correlation_id, model_name="",
    ) -> AiInteraction:
        interaction = AiInteraction.objects.create(
            actor=actor,
            patient=patient,
            kind=kind,
            status=status,
            prompt_summary=question[:500],
            context_refs=context_refs,
            model_name=model_name,
            output_text=output_text,
            output_flags=flags,
            correlation_id=correlation_id,
        )
        audit_service.record(
            audit.AI_INTERACTION, actor=actor, resource=interaction,
            metadata={"kind": kind, "status": status, "context_blocks": len(context_refs)},
        )
        return interaction

    @staticmethod
    def _contains_disallowed(text: str) -> bool:
        low = text.lower()
        return any(phrase in low for phrase in _DISALLOWED_PHRASES)
