"""Contracts for the AI assistant endpoint (spec sections 36-38).

The service receives an already-minimized, patient-scoped context assembled by
Django. It never fetches anything and holds no database access. Its answer is
extractive: it restates only what the context contains, clearly separated into
OBSERVED DATA / AI SUMMARY / INTERPRETATION / UNCERTAINTY / MISSING
INFORMATION, and never invents a medical fact.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class AiKind(str, Enum):  # noqa: UP042 - str mixin is the wire contract
    REPORT_SUMMARY = "REPORT_SUMMARY"
    HISTORY_SUMMARY = "HISTORY_SUMMARY"
    PLAIN_LANGUAGE = "PLAIN_LANGUAGE"
    QA = "QA"
    DOC_ASSIST = "DOC_ASSIST"


class ContextBlock(BaseModel):
    ref: str = Field(description="Opaque reference id assigned by Django")
    type: str = Field(description="e.g. lab_result, condition, medication, measurement, report_test")
    label: str
    content: str
    state: str = "OBSERVED"
    observed_at: str | None = None


class KnowledgeDoc(BaseModel):
    title: str
    body: str


class AiAnswerRequest(BaseModel):
    kind: AiKind
    question: str
    context_blocks: list[ContextBlock] = Field(default_factory=list)
    knowledge: list[KnowledgeDoc] = Field(default_factory=list)
    correlation_id: str


class AiAnswerSections(BaseModel):
    observed_data: list[str] = Field(default_factory=list)
    ai_summary: str = ""
    interpretation: str = ""
    uncertainty: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class AiAnswerFlags(BaseModel):
    contains_uncertainty: bool = False
    missing_information: bool = False
    distinguishes_sections: bool = True
    used_llm: bool = False
    invented_facts: bool = False


class AiAnswerResponse(BaseModel):
    status: str  # OK | INSUFFICIENT_CONTEXT
    answer: str
    sections: AiAnswerSections
    used_knowledge: list[str] = Field(default_factory=list)
    context_refs_used: list[str] = Field(default_factory=list)
    flags: AiAnswerFlags
