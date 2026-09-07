"""HTTP entry point for document intelligence.

``POST /v1/documents/process`` - Django hands over authorized document content
and gets back a structured, provenance-carrying result. This service resolves
nothing on its own: no filesystem paths, no patient lookups, no database.

``GET /v1/documents/capabilities`` - which stages can actually run in this
deployment, so availability is observable rather than assumed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from intelligence.document.ocr import available_providers, default_provider
from intelligence.document.pipeline import Disposition, process_document
from intelligence.document.wire import (
    CapabilityOut,
    DocumentProcessRequest,
    DocumentProcessResponse,
)
from intelligence.findings import build_evidence, detect
from intelligence.security import verify_service_request

router = APIRouter(tags=["documents"])

#: Which operation a disposition implies was reached, for the truncation logic.
_STAGE_OF_DISPOSITION = {
    Disposition.REJECTED_FILE: "validate_file",
    Disposition.UNREADABLE: "extract_text",
}


def _capabilities() -> dict[str, CapabilityOut]:
    try:
        provider = default_provider()
        ocr_ok = bool(provider.is_available())
        ocr_detail = (
            f"provider {provider.name}"
            if ocr_ok
            else f"no OCR engine available (default: {provider.name})"
        )
    except Exception as error:  # noqa: BLE001 - a probe must never 500
        ocr_ok, ocr_detail = False, f"probe failed: {error}"

    return {
        "pdf_text_layer": CapabilityOut(available=True, detail="pypdf"),
        "ocr": CapabilityOut(available=ocr_ok, detail=ocr_detail),
        "classification": CapabilityOut(available=True, detail="deterministic keyword vote"),
        "extraction": CapabilityOut(available=True, detail="deterministic, regex-line 1.0"),
        "finding_detection": CapabilityOut(
            available=True,
            detail=(
                "deterministic level-2 patterns and level-3 condition "
                "likelihoods over a SINGLE_REPORT timeline; every detector "
                "NOT_VALIDATED until a gold-standard set exists. Nothing here "
                "can tell a transient abnormality from a persistent one, so "
                "no finding may be read as a chronic condition"
            ),
        ),
        "llm": CapabilityOut(available=False, detail="not implemented; fails closed"),
        "rag": CapabilityOut(available=False, detail="not implemented; fails closed"),
    }


@router.get("/documents/capabilities")
async def capabilities(
    _correlation_id: str = Depends(verify_service_request),
) -> dict[str, object]:
    return {
        "ocr_providers": available_providers(),
        "capabilities": {k: v.model_dump() for k, v in _capabilities().items()},
    }


@router.post("/documents/process", response_model=DocumentProcessResponse)
async def process(
    payload: DocumentProcessRequest,
    _correlation_id: str = Depends(verify_service_request),
) -> DocumentProcessResponse:
    try:
        content = payload.decoded_content()
    except ValueError as error:
        # 422: the request was well-formed but the content it carried is not
        # something this service can process.
        raise HTTPException(status_code=422, detail=str(error)) from error

    result = process_document(
        content,
        declared_type=payload.declared_media_type,
    )

    # Honour requested_operations by blanking anything past the last stage the
    # caller asked for. The pipeline is cheap and deterministic, so it always
    # runs in full; this only controls what is returned.
    _truncate(result, payload.requested_operations)

    findings = None
    if "detect_findings" in payload.requested_operations and result.values:
        evidence = build_evidence(
            result.values,
            sex=payload.patient_sex or None,
            age_years=payload.patient_age_years,
        )
        findings = detect(evidence)

    return DocumentProcessResponse.of(
        payload.document_id, result, _capabilities(), findings
    )


def _truncate(result, operations: list[str]) -> None:
    from intelligence.document.wire import OPERATIONS

    last = max((OPERATIONS.index(op) for op in operations), default=len(OPERATIONS) - 1)
    if last < OPERATIONS.index("classify"):
        result.classification = None
        result.report_type = None
    if last < OPERATIONS.index("extract_values"):
        result.values = []
        result.completeness = None
    elif last < OPERATIONS.index("validate"):
        # Keep extracted values but drop the schema completeness verdict.
        result.completeness = None
