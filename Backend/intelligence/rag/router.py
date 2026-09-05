"""AI assistant / RAG endpoint (spec sections 36-38).

Requires the shared service token + correlation id (like every intelligence
endpoint). Makes no authorization decisions and has no database access -
Django assembles and minimizes the patient-scoped context before calling
here, and validates + records the output afterwards.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from intelligence.rag.schemas import AiAnswerRequest, AiAnswerResponse
from intelligence.rag.summarizer import summarize
from intelligence.security import verify_service_request

router = APIRouter(tags=["ai"])


@router.post("/ai/answer", response_model=AiAnswerResponse)
async def answer(
    payload: AiAnswerRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> AiAnswerResponse:
    return summarize(payload)
