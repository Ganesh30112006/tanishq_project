"""The HTTP contract for document processing.

Django is the only caller. It sends the document *content* it has already
authorized - never a filesystem path or a patient identifier this service
could use to fetch something itself. This service returns a structured result;
Django alone decides what to persist and which workflow to open.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from pydantic import BaseModel, Field, field_validator

from intelligence.document.pipeline import DocumentResult
from intelligence.document.provenance.record import Provenance
from intelligence.document.validation.checks import ValidatedValue

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024

#: Stages a caller may ask to stop after. Anything later than the last requested
#: stage is skipped. Order matters.
OPERATIONS = ("validate_file", "extract_text", "classify", "extract_values", "validate")


class DocumentProcessRequest(BaseModel):
    #: Opaque id echoed back so Django can correlate the response with its own
    #: record. This service never dereferences it.
    document_id: str = Field(min_length=1, max_length=200)
    #: The document bytes, base64-encoded. This IS the scoped payload: Django
    #: has resolved authorization and is handing over content, not a pointer.
    content_base64: str = Field(min_length=1)
    declared_media_type: str = ""
    #: Optional hint. The deterministic classifier still runs and may disagree.
    document_type_hint: str = ""
    requested_operations: list[str] = Field(default_factory=lambda: list(OPERATIONS))
    correlation_id: str = Field(min_length=1)

    @field_validator("requested_operations")
    @classmethod
    def _known_ops(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(OPERATIONS))
        if unknown:
            raise ValueError(f"unknown operations: {unknown}; allowed: {list(OPERATIONS)}")
        return value or list(OPERATIONS)

    def decoded_content(self) -> bytes:
        try:
            raw = base64.b64decode(self.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError(f"content_base64 is not valid base64: {error}") from error
        if not raw:
            raise ValueError("content_base64 decodes to zero bytes")
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")
        return raw


# --- response ------------------------------------------------------
class IssueOut(BaseModel):
    code: str
    severity: str
    detail: str = ""


class ReferenceRangeOut(BaseModel):
    text: str
    low: float | None = None
    high: float | None = None
    kind: str


class NormalizedOut(BaseModel):
    value: float | None
    unit: str
    rule_version: str
    convertible: bool
    detail: str = ""


class ProvenanceOut(BaseModel):
    source_sha256: str
    page: int
    section: str
    char_span: tuple[int, int]
    source_text: str
    text_source: str
    ocr_provider: str
    extractor: str
    extractor_version: str
    ocr_confidence: float | None
    extraction_confidence: float

    @classmethod
    def of(cls, prov: Provenance) -> ProvenanceOut:
        return cls(
            source_sha256=prov.source_sha256, page=prov.page, section=prov.section,
            char_span=prov.char_span, source_text=prov.source_text,
            text_source=prov.text_source.value, ocr_provider=prov.ocr_provider,
            extractor=prov.extractor, extractor_version=prov.extractor_version,
            ocr_confidence=prov.ocr_confidence,
            extraction_confidence=prov.extraction_confidence,
        )


class ValueOut(BaseModel):
    analyte: str | None
    printed_label: str
    value: float | None
    unit: str
    normalized: NormalizedOut | None
    reference_range: ReferenceRangeOut
    reference_status: str
    printed_flag: str
    status: str
    issues: list[str]
    provenance: ProvenanceOut

    @classmethod
    def of(cls, value: ValidatedValue, prov: Provenance) -> ValueOut:
        norm = None
        if value.normalized is not None:
            norm = NormalizedOut(
                value=value.normalized.value, unit=value.normalized.unit,
                rule_version=value.normalized.rule_version,
                convertible=value.normalized.convertible,
                detail=value.normalized.detail,
            )
        return cls(
            analyte=value.analyte, printed_label=value.printed_label,
            value=value.value, unit=value.unit, normalized=norm,
            reference_range=ReferenceRangeOut(
                text=value.reference.text, low=value.reference.low,
                high=value.reference.high, kind=value.reference.kind,
            ),
            reference_status=value.reference_status.value,
            printed_flag=value.printed_flag, status=value.status.value,
            issues=list(value.issues), provenance=ProvenanceOut.of(prov),
        )


class ClassificationOut(BaseModel):
    type: str | None
    confidence: float
    status: str
    signals: dict[str, int]
    detail: str = ""


class CompletenessOut(BaseModel):
    outcome: str
    schema_version: int
    missing_required: list[str]
    invalid: list[str]
    conflicting: list[str]
    ambiguous: list[str]
    unrecognised_labels: list[str]


class CapabilityOut(BaseModel):
    available: bool
    detail: str = ""


class DocumentProcessResponse(BaseModel):
    document_id: str
    disposition: str
    source_sha256: str
    media_type: str
    text_source: str
    ocr_outcome: str | None = None
    classification: ClassificationOut | None = None
    report_type: str | None = None
    values: list[ValueOut] = Field(default_factory=list)
    completeness: CompletenessOut | None = None
    issues: list[IssueOut] = Field(default_factory=list)
    capabilities: dict[str, CapabilityOut] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        document_id: str,
        result: DocumentResult,
        capabilities: dict[str, CapabilityOut],
    ) -> DocumentProcessResponse:
        classification = None
        if result.classification is not None:
            c = result.classification
            classification = ClassificationOut(
                type=c.report_type.value if c.report_type else None,
                confidence=c.confidence, status=c.status.value,
                signals=c.signals, detail=c.detail,
            )
        completeness = None
        if result.completeness is not None:
            comp = result.completeness
            completeness = CompletenessOut(
                outcome=comp.outcome.value, schema_version=comp.schema_version,
                missing_required=comp.missing_required, invalid=comp.invalid,
                conflicting=comp.conflicting, ambiguous=comp.ambiguous,
                unrecognised_labels=comp.unrecognised_labels,
            )
        return cls(
            document_id=document_id,
            disposition=result.disposition.value,
            source_sha256=result.source_sha256,
            media_type=result.file.media_type.value,
            text_source=result.text_source.value,
            ocr_outcome=result.ocr.outcome.value if result.ocr else None,
            classification=classification,
            report_type=result.report_type.value if result.report_type else None,
            values=[ValueOut.of(r.value, r.provenance) for r in result.values],
            completeness=completeness,
            issues=[IssueOut(code=i.code, severity=i.severity, detail=i.detail)
                    for i in result.issues],
            capabilities=capabilities,
            notes=list(result.notes),
        )


def to_dict(response: DocumentProcessResponse) -> dict[str, Any]:
    return response.model_dump()
