"""Document classification (spec section 13).

Determines what a document represents before it is interpreted. Ambiguous
documents return ``status = REVIEW_REQUIRED`` and are never confidently
processed as the wrong report type. This service returns a classification
only; Django decides what to persist.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from intelligence.schemas import ClassificationRequest, ClassificationResponse
from intelligence.security import verify_service_request

router = APIRouter(tags=["report"])

_AMBIGUITY_MARGIN = 0.15


@router.post("/classify", response_model=ClassificationResponse)
async def classify(
    payload: ClassificationRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> ClassificationResponse:
    # No trained classifier is bundled in this drop: return REVIEW_REQUIRED so
    # the document is routed to a human rather than mislabelled.
    return ClassificationResponse(
        label="OTHER",
        confidence=0.0,
        status="REVIEW_REQUIRED",
        scores={},
    )
