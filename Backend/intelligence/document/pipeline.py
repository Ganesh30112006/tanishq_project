"""Wire every deterministic stage together: bytes in, structured report out.

    bytes
      -> validate_file
      -> extract_text_layer            (PDF only)
      -> OCR                            (if there is no usable text layer)
      -> classify
      -> section tagging
      -> extract_raw_values
      -> normalise + validate each value
      -> attach provenance
      -> schema completeness roll-up

No language model is involved at any point. Every early return is a *named*
``Disposition``; the caller decides what to persist and which workflow to open.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum

from intelligence.document.classification import classify
from intelligence.document.contracts import (
    ClassificationResult,
    ClassificationStatus,
    CompletenessOutcome,
    DocumentMediaType,
    FileValidation,
    OcrOutcome,
    OcrResult,
    ReportType,
    TextLayerResult,
    TextSource,
    ValueStatus,
)
from intelligence.document.extraction import extract_raw_values
from intelligence.document.ingestion import extract_text_layer, validate_file
from intelligence.document.ocr import default_provider
from intelligence.document.ocr.provider import OcrRequest
from intelligence.document.provenance import Provenance, build_provenance
from intelligence.document.schemas import (
    CompletenessReport,
    ExtractedValue,
    assess_completeness,
    get_schema,
)
from intelligence.document.validation import ValidatedValue, validate_value

_HEADING = re.compile(r"^[A-Z][A-Z0-9 /&()\-.,]{3,}$")


class Disposition(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    #: Values were extracted and validated. Ready for the knowledge/LLM phase.
    EXTRACTED = "EXTRACTED"
    #: Text was read but no values could be extracted, or the type is unclear.
    NEEDS_REVIEW = "NEEDS_REVIEW"
    #: No text could be obtained by any available means.
    UNREADABLE = "UNREADABLE"
    #: The upload is not a report file we accept.
    REJECTED_FILE = "REJECTED_FILE"


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    severity: str  # "HIGH" | "MEDIUM" | "LOW"
    detail: str = ""


@dataclass(slots=True)
class ExtractedValueRecord:
    value: ValidatedValue
    provenance: Provenance


@dataclass(slots=True)
class DocumentResult:
    disposition: Disposition
    file: FileValidation
    source_sha256: str = ""
    text: str = ""
    text_source: TextSource = TextSource.NONE
    text_layer: TextLayerResult | None = None
    ocr: OcrResult | None = None
    classification: ClassificationResult | None = None
    report_type: ReportType | None = None
    values: list[ExtractedValueRecord] = field(default_factory=list)
    completeness: CompletenessReport | None = None
    #: How many results this document appears to hold that were **not**
    #: extracted, because classification abstained and extraction is
    #: schema-driven. A count, never the values: nothing that skipped
    #: classification may cross the boundary as a clinical fact.
    #:
    #: It is an upper bound on what was forgone, not a promise. Without a
    #: schema there are no plausibility bounds and no completeness check, so
    #: some of these would not have survived either. Recorded so that the cost
    #: of abstaining can be measured against the risk of guessing, rather than
    #: assumed either way.
    values_forgone: int = 0
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def observed_values(self) -> list[ExtractedValueRecord]:
        return [r for r in self.values if r.value.status is ValueStatus.OBSERVED]

    def outcome_for(self, analyte: str) -> ValueStatus:
        """What does this document say about ``analyte``?

        The one place ``NOT_FOUND`` is produced. A caller asking "what is the
        haemoglobin on this report?" needs to be able to tell "it is not on
        this report" from "it is on this report and we could not read it",
        and both from "the whole document was unreadable".
        """
        if self.disposition is Disposition.UNREADABLE:
            return ValueStatus.UNREADABLE
        matching = [r for r in self.values if r.value.analyte == analyte]
        if not matching:
            return ValueStatus.NOT_FOUND
        # Worst answer wins, on the same precedence the schema engine uses.
        order = [
            ValueStatus.CONFLICTING, ValueStatus.UNREADABLE, ValueStatus.INVALID,
            ValueStatus.AMBIGUOUS, ValueStatus.NEEDS_REVIEW, ValueStatus.OBSERVED,
        ]
        statuses = {r.value.status for r in matching}
        return next(status for status in order if status in statuses)


def _section_index(text: str) -> list[tuple[int, str]]:
    """(char offset, heading) for each heading line, in order."""
    marks: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if _HEADING.match(stripped) and not any(c.isdigit() for c in stripped):
            marks.append((offset, stripped))
        offset += len(line)
    return marks


def _section_for(offset: int, marks: list[tuple[int, str]]) -> str:
    name = ""
    for start, heading in marks:
        if start <= offset:
            name = heading
        else:
            break
    return name


def _count_forgone(text: str, ocr_confidence: float | None) -> int:
    """Count the results an unclassified document appears to hold.

    Extraction here is schema-driven: without a report type there is no schema,
    so the document goes to a person and yields nothing. That is the safe
    choice, and it has a price - a multi-panel report the classifier cannot
    name may carry a dozen results that would have validated perfectly.

    This counts them and throws them away. The number crosses the boundary;
    the values do not. Knowing how often abstaining costs real evidence is
    what would justify a second-stage strategy later, and guessing at that
    prevalence is how unnecessary complexity gets built.
    """
    try:
        return sum(
            1
            for raw in extract_raw_values(text)
            if validate_value(
                raw, schema=None, ocr_confidence=ocr_confidence
            ).persists_clinical_value
        )
    except Exception:  # noqa: BLE001 - a measurement may never break a document
        return 0


def process_document(
    data: bytes,
    *,
    declared_type: str = "",
    max_bytes: int = 25 * 1024 * 1024,
    ocr_provider=None,
) -> DocumentResult:
    sha256 = hashlib.sha256(data).hexdigest()
    file = validate_file(data, declared_type=declared_type, max_bytes=max_bytes)
    if not file.ok:
        return DocumentResult(
            disposition=Disposition.REJECTED_FILE, file=file, source_sha256=sha256,
            issues=[Issue("FILE_REJECTED", "HIGH", "; ".join(file.problems))],
            notes=list(file.problems),
        )

    text, source, layer, ocr = _get_text(data, file, ocr_provider)
    if not text.strip():
        detail = ocr.detail if ocr else (layer.detail if layer else "no text")
        code = ocr.outcome.value if ocr else "NO_TEXT_LAYER"
        return DocumentResult(
            disposition=Disposition.UNREADABLE, file=file, source_sha256=sha256,
            text_layer=layer, ocr=ocr,
            issues=[Issue(_ocr_issue_code(code), "HIGH", detail)],
            notes=[detail or "no text could be obtained"],
        )

    result = DocumentResult(
        disposition=Disposition.NEEDS_REVIEW, file=file, source_sha256=sha256,
        text=text, text_source=source, text_layer=layer, ocr=ocr,
    )
    if ocr is not None and ocr.outcome is OcrOutcome.LOW_CONFIDENCE:
        result.issues.append(Issue("OCR_LOW_CONFIDENCE", "MEDIUM", ocr.detail))

    classification = classify(text)
    result.classification = classification
    if classification.status is ClassificationStatus.REVIEW_REQUIRED:
        result.issues.append(
            Issue("CLASSIFICATION_REVIEW_REQUIRED", "MEDIUM", classification.detail)
        )
        result.notes.append(classification.detail)
        result.values_forgone = _count_forgone(
            text, ocr.mean_confidence if ocr else None
        )
        return result

    report_type = classification.report_type
    result.report_type = report_type
    schema = get_schema(report_type)

    marks = _section_index(text)
    page_breaks = _page_breaks(layer, ocr)
    raws = extract_raw_values(text, page_breaks=page_breaks)

    for raw in raws:
        validated = validate_value(
            raw, schema=schema,
            ocr_confidence=ocr.mean_confidence if ocr else None,
        )
        provenance = build_provenance(
            raw, source_sha256=sha256, text_source=source,
            section=_section_for(raw.char_span[0], marks),
            ocr_provider=ocr.provider if ocr else "",
            ocr_confidence=ocr.mean_confidence if ocr else None,
        )
        result.values.append(ExtractedValueRecord(validated, provenance))

    _mark_conflicts(result)

    if schema is not None:
        result.completeness = assess_completeness(
            schema,
            [
                ExtractedValue(
                    label=r.value.analyte or r.value.printed_label,
                    value=(r.value.normalized.value
                           if r.value.normalized and r.value.normalized.convertible
                           else r.value.value),
                    unit=(r.value.normalized.unit
                          if r.value.normalized and r.value.normalized.convertible
                          else r.value.unit),
                )
                for r in result.values
                if r.value.status is not ValueStatus.INVALID
            ],
        )

    _summarise(result)
    return result


def _get_text(
    data: bytes, file: FileValidation, ocr_provider
) -> tuple[str, TextSource, TextLayerResult | None, OcrResult | None]:
    layer: TextLayerResult | None = None
    if file.media_type is DocumentMediaType.PDF:
        layer = extract_text_layer(data, media_type=file.media_type)
        if layer.usable:
            return layer.text, TextSource.EMBEDDED_TEXT_LAYER, layer, None

    provider = ocr_provider or default_provider()
    ocr = provider.run(OcrRequest(image_bytes=data, media_type=file.media_type))
    if ocr.produced_text:
        return ocr.text, TextSource.OCR, layer, ocr
    return "", TextSource.NONE, layer, ocr


def _page_breaks(layer: TextLayerResult | None, ocr: OcrResult | None) -> list[int]:
    # Page mapping for OCR/text-layer output is refined in Phase 3+. For now a
    # single page is assumed unless a provider gives us more; provenance still
    # carries the token page from OCR where available.
    return []


def _ocr_issue_code(raw_code: str) -> str:
    return {
        "ENGINE_UNAVAILABLE": "OCR_UNAVAILABLE",
        "NO_TEXT_FOUND": "OCR_NO_TEXT",
        "FAILED": "OCR_FAILED",
        "NO_TEXT_LAYER": "NO_TEXT_LAYER",
    }.get(raw_code, "UNREADABLE")


def _mark_conflicts(result: DocumentResult) -> None:
    """The same analyte, twice, with different numbers.

    Neither is chosen. Picking the first, the last or the worse would each be
    a defensible-sounding rule that silently discards half of a contradiction
    the report is telling us about itself.
    """
    by_analyte: dict[str, list[ExtractedValueRecord]] = {}
    for record in result.values:
        if record.value.analyte and record.value.value is not None:
            by_analyte.setdefault(record.value.analyte, []).append(record)

    for analyte, records in by_analyte.items():
        # Compare in canonical units where possible, so "13.4 g/dL" and
        # "134 g/L" on one report are not reported as a contradiction.
        seen = {
            round(
                r.value.normalized.value
                if r.value.normalized and r.value.normalized.convertible
                else r.value.value,
                6,
            )
            for r in records
        }
        if len(seen) <= 1:
            continue
        for record in records:
            record.value.status = ValueStatus.CONFLICTING
            record.value.reason = "same_analyte_reported_with_different_values"
            record.value.issues.append(
                f"{analyte} is reported more than once on this document with "
                f"different values ({sorted(seen)}); neither is chosen"
            )


def _summarise(result: DocumentResult) -> None:
    def _with(status: ValueStatus) -> list[ExtractedValueRecord]:
        return [r for r in result.values if r.value.status is status]

    observed = result.observed_values

    for status, code, severity in (
        (ValueStatus.CONFLICTING, "VALUES_CONFLICTING", "HIGH"),
        (ValueStatus.INVALID, "VALUES_INVALID", "HIGH"),
        (ValueStatus.UNREADABLE, "VALUES_UNREADABLE", "HIGH"),
        (ValueStatus.AMBIGUOUS, "VALUES_AMBIGUOUS", "MEDIUM"),
        (ValueStatus.NEEDS_REVIEW, "VALUES_NEED_REVIEW", "MEDIUM"),
    ):
        records = _with(status)
        if records:
            result.issues.append(Issue(
                code, severity,
                ", ".join(sorted({r.value.printed_label for r in records})),
            ))
    if not result.values:
        result.issues.append(Issue("NO_VALUES_EXTRACTED", "MEDIUM", ""))

    if result.completeness is not None:
        outcome = result.completeness.outcome
        if outcome is not CompletenessOutcome.COMPLETE:
            result.issues.append(Issue(
                f"SCHEMA_{outcome.value}", "MEDIUM",
                ", ".join(
                    result.completeness.missing_required
                    + result.completeness.conflicting
                    + result.completeness.invalid
                    + result.completeness.ambiguous
                ),
            ))

    high = any(i.severity == "HIGH" for i in result.issues)
    if observed and not high and result.completeness is not None and (
        result.completeness.outcome is CompletenessOutcome.COMPLETE
    ):
        result.disposition = Disposition.EXTRACTED
    elif observed and not high and result.completeness is None:
        # A type with no schema (narrative report) but clean values extracted.
        result.disposition = Disposition.EXTRACTED
    else:
        result.disposition = Disposition.NEEDS_REVIEW
