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
OPERATIONS = (
    "validate_file", "extract_text", "classify", "extract_values", "validate",
    "detect_findings",
)


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
    #: Clinical context needed to pick a reference interval. These are
    #: attributes, not identifiers: the service cannot resolve them to a person
    #: and does not try. Sex is "male" / "female" / "" (unknown, which widens
    #: the interval and is recorded as a caveat on any finding that used it).
    patient_sex: str = ""
    patient_age_years: float | None = None
    correlation_id: str = Field(min_length=1)

    @field_validator("patient_sex")
    @classmethod
    def _known_sex(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in ("", "male", "female"):
            raise ValueError("patient_sex must be 'male', 'female' or empty")
        return cleaned

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
    #: The unit the range itself was printed in, as the laboratory wrote it.
    #: Empty when the range column carried none of its own.
    unit: str = ""


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
    #: Whether the result and its printed range could be compared at all, and
    #: on what basis: SAME_UNIT / CONVERTIBLE / INCOMPATIBLE / UNKNOWN. Sent
    #: rather than re-derived, because a caller that gets this wrong compares
    #: two different quantities and cannot tell.
    unit_relation: str
    printed_flag: str
    status: str
    #: One short machine-readable token saying why the status is what it is,
    #: so Django can route without parsing prose. Empty when OBSERVED.
    reason: str = ""
    #: Exactly one status persists a clinical value. Sent explicitly rather
    #: than left for the caller to re-derive from the status string, because
    #: getting that derivation wrong on one branch is how a value nobody
    #: trusted becomes a clinical record.
    persists_clinical_value: bool = False
    issues: list[str] = []
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
                unit=value.reference.unit,
            ),
            reference_status=value.reference_status.value,
            unit_relation=value.unit_relation.value,
            printed_flag=value.printed_flag, status=value.status.value,
            reason=value.reason,
            persists_clinical_value=value.status.persists_clinical_value,
            issues=list(value.issues), provenance=ProvenanceOut.of(prov),
        )


class EvidenceRefOut(BaseModel):
    key: str
    kind: str
    value: float | None = None
    unit: str = ""
    reference_text: str = ""
    reference_source: str = ""
    reference_status: str = ""
    page: int | None = None
    section: str = ""
    source_text: str = ""


class FindingOut(BaseModel):
    code: str
    label: str
    level: int
    category: str
    detector: str
    confidence: str
    validation_status: str
    human_review_required: bool
    explanation: str
    evidence_used: list[EvidenceRefOut] = Field(default_factory=list)
    evidence_missing: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    #: From the approved knowledge entry for ``code``, never generated. Empty
    #: when the code has no entry, so a caller shows nothing rather than prose
    #: nobody approved.
    plain_name: str = ""
    plain_explanation: str = ""
    next_steps: list[str] = Field(default_factory=list)


class FindingsOut(BaseModel):
    findings: list[FindingOut] = Field(default_factory=list)
    unusable_evidence: list[str] = Field(default_factory=list)
    detectors_run: int = 0
    range_table_version: str = ""
    knowledge_version: str = ""
    needs_human_review: bool = False


class ClassificationOut(BaseModel):
    type: str | None
    confidence: float
    status: str
    signals: dict[str, int]
    detail: str = ""
    #: Machine-readable counterpart to ``detail``.
    reason: str = ""


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
    #: Results this document appears to hold that were not extracted because
    #: classification abstained. A count, never the values.
    values_forgone: int = 0
    report_type: str | None = None
    values: list[ValueOut] = Field(default_factory=list)
    completeness: CompletenessOut | None = None
    findings: FindingsOut | None = None
    issues: list[IssueOut] = Field(default_factory=list)
    capabilities: dict[str, CapabilityOut] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def of(
        cls,
        document_id: str,
        result: DocumentResult,
        capabilities: dict[str, CapabilityOut],
        findings=None,
    ) -> DocumentProcessResponse:
        classification = None
        if result.classification is not None:
            c = result.classification
            classification = ClassificationOut(
                type=c.report_type.value if c.report_type else None,
                confidence=c.confidence, status=c.status.value,
                signals=c.signals, detail=c.detail, reason=c.reason,
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
            values_forgone=result.values_forgone,
            report_type=result.report_type.value if result.report_type else None,
            values=[ValueOut.of(r.value, r.provenance) for r in result.values],
            completeness=completeness,
            findings=findings_out(findings),
            issues=[IssueOut(code=i.code, severity=i.severity, detail=i.detail)
                    for i in result.issues],
            capabilities=capabilities,
            notes=list(result.notes),
        )


def findings_out(report) -> FindingsOut | None:
    if report is None:
        return None
    from intelligence.knowledge.findings import KNOWLEDGE_VERSION
    from intelligence.knowledge.findings import get as knowledge_for

    def _knowledge(code: str) -> dict[str, Any]:
        entry = knowledge_for(code)
        if entry is None:
            return {}
        return {
            "plain_name": entry.canonical_name,
            "plain_explanation": entry.plain_explanation,
            "next_steps": list(entry.next_steps),
        }

    return FindingsOut(
        findings=[
            FindingOut(
                code=f.code, label=f.label, level=int(f.level.value),
                category=f.category, detector=f.detector,
                confidence=f.confidence.value,
                validation_status=f.validation_status.value,
                human_review_required=f.human_review_required,
                explanation=f.explanation,
                evidence_used=[
                    EvidenceRefOut(
                        key=e.key, kind=e.kind, value=e.value, unit=e.unit,
                        reference_text=e.reference_text,
                        reference_source=e.reference_source,
                        reference_status=e.reference_status,
                        page=e.page, section=e.section,
                        source_text=e.source_text,
                    )
                    for e in f.evidence_used
                ],
                evidence_missing=list(f.evidence_missing),
                caveats=list(f.caveats),
                **_knowledge(f.code),
            )
            for f in report.findings
        ],
        unusable_evidence=list(report.unusable_evidence),
        detectors_run=report.detectors_run,
        range_table_version=report.range_table_version,
        knowledge_version=KNOWLEDGE_VERSION,
        needs_human_review=report.needs_human_review,
    )


def to_dict(response: DocumentProcessResponse) -> dict[str, Any]:
    return response.model_dump()
