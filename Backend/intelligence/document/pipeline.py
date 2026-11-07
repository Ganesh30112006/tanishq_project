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
from dataclasses import dataclass, field, replace
from enum import Enum

from intelligence.document.classification import classify
from intelligence.document.classification.panels import (
    URINE_ANALYTES,
    first_panel_offset,
    headings,
    in_non_blood_section,
    multi_panel,
)
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


#: How sure OCR must be of the very number it read. The page's average does not
#: answer this: a misread AST of 215 for 27.5 sat on a page averaging 0.85. Two
#: misreads were seen on rendered reports, at 0.86 and 0.93 (an ALP of 147 as 447);
#: this floor kept 108 of 114 correct numbers on low-quality scans. Two misreads
#: are thin evidence and a digit can be misread confidently, so this is a guard,
#: not a measurement of OCR accuracy: the screen also tells the patient to check a
#: scan's numbers against the printed report. A gold corpus should re-set it.
OCR_NUMBER_FLOOR = 0.94


def _number_confidence(ocr: OcrResult, raw) -> float | None:
    """OCR's confidence in this value's number. None if the engine gives no spans.

    0.0 when it gives spans but none holds the number: the row was rebuilt from
    words, so a number that cannot be found among them cannot be vouched for.
    """
    if not ocr.word_spans:
        return None
    start, end = raw.char_span
    found = [
        confidence
        for word_start, word_end, confidence in ocr.word_spans
        if start <= word_start < end and raw.value_text in ocr.text[word_start:word_end]
    ]
    return min(found, default=0.0)


def _refuse(validated: ValidatedValue, reason: str, why: str) -> None:
    """Withdraw a value's identity: what it measured is not what its name says.

    The analyte is cleared as well as the status, so a urine creatinine cannot
    go on to "conflict" with - and knock out - the serum creatinine that is
    on the same report.
    """
    validated.issues.append(f"{validated.analyte or validated.printed_label} {why}")
    validated.analyte = None
    validated.status = ValueStatus.AMBIGUOUS
    validated.reason = reason


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

    Without a report type, a document that is not a recognisable multi-panel
    report goes to a person and yields nothing. That is the safe choice, and
    it has a price - such a document may carry results that would have
    validated perfectly.

    This counts them and throws them away. The number crosses the boundary;
    the values do not. It is how the multi-panel reading was justified: on the
    laboratory sample reports measured on 2026-11-02, nine in thirteen were
    health checks this count said were being lost.
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
    marks = headings(text)
    panels = multi_panel(text, classification, marks)
    if panels:
        classification = replace(
            classification, status=ClassificationStatus.MULTI_PANEL,
            report_type=None, reason="several_panels", panels=panels,
            detail="several panels: " + ", ".join(p.value for p in panels),
        )
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
    schema = get_schema(report_type) if report_type else None

    sections = _section_index(text)
    page_breaks = _page_breaks(layer, ocr)
    raws = extract_raw_values(text, page_breaks=page_breaks)
    # Nothing above a multi-panel report's first panel heading is read: that
    # is the patient block, where the document has not yet said what follows.
    first_panel = first_panel_offset(marks) if panels else None

    for raw in raws:
        validated = validate_value(
            raw, schema=schema,
            ocr_confidence=ocr.mean_confidence if ocr else None,
        )
        at = raw.char_span[0]
        if first_panel is not None and at < first_panel:
            _refuse(validated, "outside_any_panel",
                    "printed above the report's first panel heading")
        elif validated.analyte and validated.analyte not in URINE_ANALYTES and (
            in_non_blood_section(
                at, marks, starts_non_blood=report_type is ReportType.URINALYSIS,
            )
        ):
            _refuse(validated, "not_a_blood_sample",
                    "printed under a heading that names a non-blood sample")
        elif ocr is not None and validated.persists_clinical_value:
            confidence = _number_confidence(ocr, raw)
            if confidence is not None and confidence < OCR_NUMBER_FLOOR:
                _refuse(validated, "ocr_number_uncertain",
                        f"was read by OCR with only {confidence:.2f} confidence in the number")
        provenance = build_provenance(
            raw, source_sha256=sha256, text_source=source,
            section=_section_for(at, sections),
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
    """Where pages two onward begin in the text the values were read from."""
    source = ocr if ocr is not None and ocr.produced_text else layer
    starts = source.page_starts if source is not None else ()
    return list(starts[1:])


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

    multi = (
        result.classification is not None
        and result.classification.status is ClassificationStatus.MULTI_PANEL
    )
    if multi:
        result.issues.append(Issue(
            "MULTI_PANEL_REPORT", "LOW",
            ", ".join(p.value for p in result.classification.panels),
        ))

    high = any(i.severity == "HIGH" for i in result.issues)
    if multi:
        # Each value stands on its own checks; no schema says what the whole
        # document should hold, so the document as a whole is never "complete".
        result.disposition = Disposition.NEEDS_REVIEW
    elif observed and not high and result.completeness is not None and (
        result.completeness.outcome is CompletenessOutcome.COMPLETE
    ):
        result.disposition = Disposition.EXTRACTED
    elif observed and not high and result.completeness is None:
        # A type with no schema (narrative report) but clean values extracted.
        result.disposition = Disposition.EXTRACTED
    else:
        result.disposition = Disposition.NEEDS_REVIEW
