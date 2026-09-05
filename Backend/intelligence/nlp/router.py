"""NLP / entity extraction (spec sections 12, 15).

Extracts candidate entities (test names, values, units, dates) with per-field
confidence and negation / uncertainty flags. Entity-extraction confidence is
kept separate from OCR confidence and from value validation - a value can be
read with high confidence yet be medically invalid. Uncertain or negated
mentions are flagged, never turned into measurements.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from intelligence.nlp.extractor import extract
from intelligence.security import verify_service_request

router = APIRouter(tags=["nlp"])


class ExtractionRequest(BaseModel):
    text: str
    report_class: str | None = None
    correlation_id: str


class ExtractedEntity(BaseModel):
    kind: str
    analyte: str
    text: str
    value: float | None = None
    unit: str = ""
    entity_confidence: float
    context_confidence: float
    negated: bool = False
    uncertain: bool = False


class ExtractionResponse(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    status: str


@router.post("/extract", response_model=ExtractionResponse)
async def extract_entities(
    payload: ExtractionRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> ExtractionResponse:
    result = extract(payload.text)
    return ExtractionResponse(
        entities=[
            ExtractedEntity(
                kind=e.kind, analyte=e.analyte, text=e.text, value=e.value, unit=e.unit,
                entity_confidence=e.entity_confidence, context_confidence=e.context_confidence,
                negated=e.negated, uncertain=e.uncertain,
            )
            for e in result.entities
        ],
        status=result.status,
    )
