"""Deterministic extractive summarizer (spec sections 36-38).

This stands in for an LLM behind a fixed contract. It restates *only* what the
provided context contains and never generates a medical fact that is not
present. A real LLM can replace :func:`summarize` as long as its output passes
the same validation and is presented with the same OBSERVED / SUMMARY /
INTERPRETATION / UNCERTAINTY / MISSING labelling. It is deliberately NOT a
risk predictor and offers no clinical interpretation.
"""
from __future__ import annotations

import re

from intelligence.rag.schemas import (
    AiAnswerFlags,
    AiAnswerRequest,
    AiAnswerResponse,
    AiAnswerSections,
    ContextBlock,
)

TRUSTWORTHY = {"OBSERVED", "DERIVED"}

# Topics a question may ask about, and the words that signal them.
_TOPIC_WORDS = {
    "glucose": ("glucose", "sugar", "fbs"),
    "hba1c": ("hba1c", "a1c", "glycated"),
    "cholesterol": ("cholesterol", "lipid", "hdl", "ldl", "triglyceride"),
    "blood pressure": ("blood pressure", "bp", "systolic", "diastolic", "hypertension"),
    "kidney": ("kidney", "creatinine", "egfr", "renal"),
    "medication": ("medication", "drug", "prescription", "dose"),
    "condition": ("condition", "diagnosis", "history", "problem"),
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _mentioned_topics(question: str) -> set[str]:
    q = question.lower()
    return {topic for topic, words in _TOPIC_WORDS.items() if any(w in q for w in words)}


def _block_line(b: ContextBlock) -> str:
    when = f" (observed {b.observed_at})" if b.observed_at else ""
    return f"{b.label}: {b.content}{when}"


def _rank_knowledge(question: str, docs) -> list:
    q = _tokens(question)
    scored = [(len(q & _tokens(d.title + " " + d.body)), d) for d in docs]
    scored = [pair for pair in scored if pair[0] > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [d for _, d in scored[:3]]


def summarize(req: AiAnswerRequest) -> AiAnswerResponse:
    observed = [b for b in req.context_blocks if b.state in TRUSTWORTHY]
    non_observed = [b for b in req.context_blocks if b.state not in TRUSTWORTHY]

    topics = _mentioned_topics(req.question)
    relevant = observed
    if topics:
        filtered = [b for b in observed if any(t.split()[0] in (b.label + " " + b.type).lower() for t in topics)]
        if filtered:
            relevant = filtered

    knowledge = _rank_knowledge(req.question, req.knowledge)

    sections = AiAnswerSections()
    sections.observed_data = [_block_line(b) for b in relevant]
    sections.uncertainty = [
        f"{b.label}: value present but state is {b.state}; not treated as an observed measurement."
        for b in non_observed
    ]
    sections.references = [d.title for d in knowledge]

    # MISSING INFORMATION: topics the question asked about with no observed block.
    covered = {(b.label + " " + b.type).lower() for b in observed}
    sections.missing_information = [
        f"No observed data for '{topic}' is available in the authorized record."
        for topic in sorted(topics)
        if not any(topic.split()[0] in c for c in covered)
    ]

    has_content = bool(relevant) or bool(knowledge)
    if not has_content:
        sections.ai_summary = (
            "The authorized record does not contain information needed to answer this "
            "question. No answer is generated."
        )
        return AiAnswerResponse(
            status="INSUFFICIENT_CONTEXT",
            answer=sections.ai_summary,
            sections=sections,
            used_knowledge=[],
            context_refs_used=[],
            flags=AiAnswerFlags(
                contains_uncertainty=bool(sections.uncertainty),
                missing_information=True,
            ),
        )

    if relevant:
        latest = max(relevant, key=lambda b: b.observed_at or "")
        sections.ai_summary = (
            f"Based on {len(relevant)} observed value(s) provided from the authorized "
            f"record, the most recent relevant entry is {_block_line(latest)}. "
            "This is a restatement of recorded data, not a clinical interpretation."
        )
    else:
        sections.ai_summary = (
            "No patient-specific observed values matched this question; only approved "
            "general reference material is included below."
        )
    sections.interpretation = "This assistant does not provide clinical interpretation or diagnosis."

    answer = _render(sections)
    return AiAnswerResponse(
        status="OK",
        answer=answer,
        sections=sections,
        used_knowledge=[d.title for d in knowledge],
        context_refs_used=[b.ref for b in relevant],
        flags=AiAnswerFlags(
            contains_uncertainty=bool(sections.uncertainty),
            missing_information=bool(sections.missing_information),
        ),
    )


def _render(s: AiAnswerSections) -> str:
    parts = []
    if s.observed_data:
        parts.append("OBSERVED DATA:\n" + "\n".join(f"- {line}" for line in s.observed_data))
    parts.append("AI SUMMARY:\n" + s.ai_summary)
    if s.interpretation:
        parts.append("INTERPRETATION:\n" + s.interpretation)
    if s.uncertainty:
        parts.append("UNCERTAINTY:\n" + "\n".join(f"- {line}" for line in s.uncertainty))
    if s.missing_information:
        parts.append("MISSING INFORMATION:\n" + "\n".join(f"- {line}" for line in s.missing_information))
    if s.references:
        parts.append("REFERENCES (general knowledge, not patient-specific):\n"
                     + "\n".join(f"- {title}" for title in s.references))
    return "\n\n".join(parts)
