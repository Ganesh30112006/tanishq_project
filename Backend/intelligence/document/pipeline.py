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
    ReferenceStatus,
    ReportType,
    TextLayerResult,
    TextSource,
    ValueStatus,
)
from intelligence.document.extraction import extract_raw_values
from intelligence.document.extraction.analytes import RawExtraction
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
#: When two different readings of the page give the same number and the same place
#: against the range, the number needs only this. Two independent readings making the
#: same mistake is far less likely than one reading being confidently wrong.
OCR_AGREED_FLOOR = 0.60
#: Tests whose true result can be exactly 0. For any other test a 0 from a picture is
#: a covered digit: a watermark over "30.0" read as 0.0 in both readings.
CAN_BE_ZERO = frozenset({"basophils", "eosinophils", "monocytes", "bilirubin_direct"})
_OUTSIDE_RANGE = (ReferenceStatus.ABOVE, ReferenceStatus.BELOW)
#: On a picture, a result this many times beyond its printed range is held. A flag
#: printed against the number turns "48 ↑" into 481 in every reading, so agreement
#: cannot catch it. A true result this extreme is still named in the warning, and a
#: dangerous one still gets the urgent message.
OCR_FAR_OUTSIDE = 8.0


def _far_outside(validated: ValidatedValue) -> bool:
    value, ref = validated.value, validated.reference
    if value is None or not ref.is_numeric or not validated.unit_relation.comparable:
        return False
    if ref.high is not None and ref.high > 0 and value > OCR_FAR_OUTSIDE * ref.high:
        return True
    return ref.low is not None and ref.low > 0 and value < ref.low / OCR_FAR_OUTSIDE


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


def _row_confidence(ocr: OcrResult | None, raw) -> float | None:
    """OCR's mean confidence in the words of this value's own row.

    The page's mean is the wrong measure: a QR code or a busy letterhead pulls a
    clean table below the floor, and one clean page average lets a garbled row
    through. The page mean is the fallback when the engine gives no word spans.
    """
    if ocr is None:
        return None
    if not ocr.word_spans:
        return ocr.mean_confidence
    start, end = raw.char_span
    found = [confidence for word_start, _, confidence in ocr.word_spans if start <= word_start < end]
    return sum(found) / len(found) if found else 0.0


def _placement_refusal(
    validated: ValidatedValue, at: int, marks, first_panel: int | None, report_type,
) -> tuple[str, str] | None:
    """(reason, why) if where the value is printed means it cannot be used."""
    if first_panel is not None and at < first_panel:
        return "outside_any_panel", "printed above the report's first panel heading"
    if validated.analyte and validated.analyte not in URINE_ANALYTES and in_non_blood_section(
        at, marks, starts_non_blood=report_type is ReportType.URINALYSIS,
    ):
        return "not_a_blood_sample", "printed under a heading that names a non-blood sample"
    return None


def _second_reading_values(
    second: OcrResult, *, schema, panels, report_type,
) -> list[tuple[RawExtraction, ValidatedValue]]:
    """The values the second reading of the page stands behind."""
    marks = headings(second.text)
    first_panel = first_panel_offset(marks) if panels else None
    out = []
    for raw in extract_raw_values(second.text, page_breaks=_page_breaks(None, second)):
        validated = validate_value(raw, schema=schema, ocr_confidence=_row_confidence(second, raw))
        if not validated.persists_clinical_value or not validated.analyte:
            continue
        if _placement_refusal(validated, raw.char_span[0], marks, first_panel, report_type) is None:
            out.append((raw, validated))
    return out


def _check_ocr_number(
    validated: ValidatedValue, ocr: OcrResult, raw, second_values, stamp_free_values,
) -> tuple[str, str] | None:
    """(reason, why) if this OCR value cannot be trusted, else None.

    With a second reading of the same test, agreement decides. It covers the range
    too: a range read as 45-55 for 4.5-5.5 calls a normal value low. The colour-free
    reading can agree, but disagreeing with it means nothing.
    """
    if validated.value == 0 and validated.analyte not in CAN_BE_ZERO:
        return "ocr_number_uncertain", "was read from a picture as exactly 0, which usually means a covered digit"
    confidence = _number_confidence(ocr, raw)
    analyte = validated.analyte
    others = [v for _, v in second_values if v.analyte == analyte]
    same = [
        v for _, v in [*second_values, *stamp_free_values]
        if v.analyte == analyte and v.value == validated.value
    ]
    if not same:
        if others:
            return "ocr_readings_disagree", "was read as a different number by the second reading of the page"
        if _far_outside(validated):
            return "ocr_number_uncertain", "is so far outside its range that, on a picture, it is more likely misread"
        if confidence is not None and confidence < OCR_NUMBER_FLOOR:
            return "ocr_number_uncertain", f"was read by OCR with only {confidence:.2f} confidence in the number"
        if ocr.second is not None and validated.reference_status in _OUTSIDE_RANGE:
            # The patient is still told, by the warning on values not used.
            return "ocr_number_uncertain", "looks abnormal, but only one reading of the page saw this number"
        return None
    if all(v.reference_status is not validated.reference_status for v in same):
        return "ocr_readings_disagree", "was placed differently against its range by the second reading of the page"
    if _far_outside(validated):
        return "ocr_number_uncertain", "is so far outside its range that, on a picture, it is more likely misread"
    if confidence is not None and confidence < OCR_AGREED_FLOOR:
        return "ocr_number_uncertain", f"was read by OCR with only {confidence:.2f} confidence in the number"
    return None


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

    second = ocr.second if ocr is not None else None
    second_values = _second_reading_values(
        second, schema=schema, panels=panels, report_type=report_type,
    ) if second is not None else []
    stamp_free = ocr.stamp_free if ocr is not None else None
    stamp_free_values = _second_reading_values(
        stamp_free, schema=schema, panels=panels, report_type=report_type,
    ) if stamp_free is not None else []
    numbers_read: dict[str, set[float]] = {}
    disputed: set[str] = set()

    for raw in raws:
        validated = validate_value(raw, schema=schema, ocr_confidence=_row_confidence(ocr, raw))
        at = raw.char_span[0]
        analyte = validated.analyte
        if analyte and validated.value is not None:
            numbers_read.setdefault(analyte, set()).add(validated.value)
        refusal = _placement_refusal(validated, at, marks, first_panel, report_type)
        if refusal is None and ocr is not None and validated.persists_clinical_value:
            refusal = _check_ocr_number(validated, ocr, raw, second_values, stamp_free_values)
        if refusal is not None:
            if refusal[0] == "ocr_readings_disagree":
                disputed.add(analyte)
            _refuse(validated, *refusal)
        provenance = build_provenance(
            raw, source_sha256=sha256, text_source=source,
            section=_section_for(at, sections),
            ocr_provider=ocr.provider if ocr else "",
            ocr_confidence=ocr.mean_confidence if ocr else None,
        )
        result.values.append(ExtractedValueRecord(validated, provenance))

    for other, other_values in ((second, second_values), (stamp_free, stamp_free_values)):
        if other is not None:
            _add_from_second_reading(
                result, other, other_values, numbers_read, disputed,
                sha256=sha256, source=source, provider=ocr.provider,
            )

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


def _add_from_second_reading(
    result: DocumentResult, second: OcrResult, second_values, numbers_read, disputed,
    *, sha256: str, source, provider: str,
) -> None:
    """Tests only the second reading could use: the first lost a unit, say, or a row.

    If the first reading saw a number for the test it must be this same number. If it
    saw none, this reading has to be sure of the number on its own.
    """
    used = {r.value.analyte for r in result.values if r.value.persists_clinical_value}
    added: set[tuple[str, float | None]] = set()
    sections = _section_index(second.text)
    shift = len(result.text) + 1
    for raw, validated in second_values:
        analyte = validated.analyte
        pair = (analyte, validated.value)
        if analyte in used or analyte in disputed or pair in added:
            continue
        first = numbers_read.get(analyte, set())
        if first and validated.value not in first:
            continue
        if validated.value == 0 and analyte not in CAN_BE_ZERO:
            continue
        if _far_outside(validated):
            added.add(pair)
            _refuse(validated, "ocr_number_uncertain",
                    "is so far outside its range that, on a picture, it is more likely misread")
            result.values.append(ExtractedValueRecord(validated, build_provenance(
                replace(raw, char_span=(raw.char_span[0] + shift, raw.char_span[1] + shift)),
                source_sha256=sha256, text_source=source, section=_section_for(raw.char_span[0], sections),
                ocr_provider=provider, ocr_confidence=second.mean_confidence,
            )))
            continue
        confidence = _number_confidence(second, raw)
        floor = OCR_AGREED_FLOOR if first else OCR_NUMBER_FLOOR
        if confidence is not None and confidence < floor:
            continue
        added.add(pair)
        if not first and validated.reference_status in _OUTSIDE_RANGE:
            # Seen by this reading alone: held back, but the warning still names it.
            _refuse(validated, "ocr_number_uncertain",
                    "looks abnormal, but only one reading of the page saw this number")
        # The first reading's row for this test could not be used, and this one
        # replaces it. Left in, its unconverted number would "conflict" with this.
        result.values = [
            r for r in result.values
            if r.value.analyte != analyte or r.value.persists_clinical_value
        ]
        provenance = build_provenance(
            replace(raw, char_span=(raw.char_span[0] + shift, raw.char_span[1] + shift)),
            source_sha256=sha256, text_source=source,
            section=_section_for(raw.char_span[0], sections),
            ocr_provider=provider, ocr_confidence=second.mean_confidence,
        )
        result.values.append(ExtractedValueRecord(validated, provenance))
    if added:
        # So that a value's offsets point at the words it came from.
        result.text = f"{result.text}\n{second.text}"


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
