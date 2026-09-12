"""Deterministic report-processing pipeline (spec section 12).

    FILE -> TEXT/OCR -> CLASSIFICATION -> SECTION DETECTION -> ENTITY EXTRACTION
    -> TERMINOLOGY NORMALIZATION -> UNIT NORMALIZATION -> TEMPORAL EXTRACTION
    -> DETERMINISTIC VALIDATION -> COMPLETENESS ANALYSIS -> PROVENANCE
    -> RECONCILIATION -> HUMAN REVIEW WHEN REQUIRED -> FINALIZED

Every stage is deterministic. The intelligence service may assist with OCR /
classification / entity extraction, but no value it proposes becomes trusted
until it passes deterministic validation here. Conflicts are never resolved
silently - both values are preserved and a reconciliation event is opened.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.services import audit_service
from apps.common.enums import (
    ClinicalDataState,
    CompletenessStatus,
    ExtractionMethod,
    ReportClass,
    ReportProcessingState,
    ValidationStatus,
)
from apps.common.services import BaseService, ServiceResult
from apps.common.units import convert
from apps.medical_records.models import Provenance
from apps.reconciliation.services import ReconciliationService
from apps.reports import second_reader
from apps.reports.extraction import extract_text
from apps.reports.models import Report, ReportSection, ReportTest
from apps.reports.ocr import read_report_bytes
from apps.reports.schema_engine import SchemaEngine, active_schema

_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&()\-]{3,}$")
_DATE_LABELS = {
    "collected_at": ("collected", "specimen collected", "collection date", "drawn"),
    "reported_at": ("reported", "report date", "verified", "released"),
}
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\d{2}/\d{2}/\d{4})"
)


@dataclass(slots=True)
class PipelineResult:
    report: Report
    state: str
    review_reason: str = ""


class ReportPipeline(BaseService):
    def __init__(self, *, reconciliation: ReconciliationService | None = None) -> None:
        self.schema_engine = SchemaEngine()
        self.reconciliation = reconciliation or ReconciliationService()

    @transaction.atomic
    def run(self, report: Report) -> ServiceResult[PipelineResult]:
        report = Report.objects.select_for_update().get(pk=report.pk)

        # Idempotency: a finalized/rejected report is not re-processed.
        if report.processing_state in (
            ReportProcessingState.FINALIZED,
            ReportProcessingState.REJECTED,
        ):
            return ServiceResult.success(PipelineResult(report, report.processing_state))

        text = self._load_text(report)
        if not text:
            return self._review(report, "Report text is unavailable or unreadable.")

        report_class, class_conf = self._classify(report, text)
        report.report_class = report_class
        report.classification_confidence = class_conf
        if report_class == ReportClass.OTHER and not report.class_hint:
            return self._review(report, "Document type could not be determined with confidence.")

        schema = active_schema(report_class)
        report.schema = schema

        self._detect_sections(report, text)
        extraction = extract_text(text)
        tests = self._materialize_tests(report, extraction, schema)
        self._extract_temporal(report, text)
        self._validate(tests, schema)
        self._write_provenance(report, tests)

        comparison = None
        if schema is not None:
            comparison = self.schema_engine.compare(
                schema=schema, values_by_field=self._values_by_field(tests)
            )
            report.completeness_status = comparison.status
        else:
            report.completeness_status = CompletenessStatus.AMBIGUOUS

        conflicts = self._reconcile(report, tests)

        finalizable = (
            comparison is not None
            and comparison.status == CompletenessStatus.COMPLETE
            and not conflicts
            and all(t.validation_status == ValidationStatus.PASSED for t in tests)
        )

        # A second reader that may only make the outcome more conservative.
        # Consulted after the decision is already made, and able to change it
        # in exactly one direction: a report this pipeline would finalize can
        # be held, and a report it would hold can never be finalized. Nothing
        # the service returns is persisted as a clinical value.
        opinion = self._second_opinion(report)
        if finalizable and second_reader.mode() == second_reader.ADVISORY and (
            opinion.holds_report
        ):
            return self._review(
                report,
                "A second reading of this document raised concerns: "
                + "; ".join(opinion.concerns),
                report_class=report_class,
                second_opinion=opinion,
            )

        if finalizable:
            report.processing_state = ReportProcessingState.FINALIZED
            report.validation_status = ValidationStatus.PASSED
            report.review_reason = ""
            report.save()
            audit_service.record(
                audit.REPORT_PROCESSED, resource=report,
                metadata={
                    "outcome": "FINALIZED", "report_class": report_class,
                    "second_reader": opinion.as_audit_metadata(),
                },
            )
            return ServiceResult.success(PipelineResult(report, report.processing_state))

        reason = self._review_reason(comparison, conflicts, tests)
        return self._review(
            report, reason, report_class=report_class, second_opinion=opinion
        )

    # ------------------------------------------------------------------
    def _load_text(self, report: Report) -> str:
        """Use text already attached (from a prior OCR step or a text upload),
        otherwise extract it from the stored file now and persist it so the
        structured result stays reproducible (spec section 34)."""
        if report.extracted_text.strip():
            return report.extracted_text.strip()
        from apps.reports.ocr import extract_text_from_report

        text = extract_text_from_report(report)
        if text:
            report.extracted_text = text
            report.save(update_fields=["extracted_text", "updated_at"])
        return text.strip()

    def _classify(self, report: Report, text: str) -> tuple[str, float]:
        if report.class_hint:
            # Uploader assertion is authoritative but still schema-checked.
            return report.class_hint, 1.0
        # Deterministic keyword vote as a first pass; the intelligence service
        # classifier would refine this. Ambiguous -> OTHER (REVIEW_REQUIRED).
        lowered = text.lower()
        votes = {
            ReportClass.HBA1C: lowered.count("a1c") + lowered.count("glycated"),
            ReportClass.GLUCOSE: lowered.count("glucose") + lowered.count("blood sugar"),
            ReportClass.LIPID: sum(lowered.count(k) for k in ("cholesterol", "hdl", "ldl", "triglyceride")),
            ReportClass.CBC: sum(lowered.count(k) for k in ("hemoglobin", "haemoglobin", "wbc", "platelet")),
        }
        best, score = max(votes.items(), key=lambda kv: kv[1])
        runner_up = sorted(votes.values(), reverse=True)[1] if len(votes) > 1 else 0
        if score == 0 or score == runner_up:
            return ReportClass.OTHER, 0.2
        return best, min(0.5 + 0.1 * score, 0.9)

    def _detect_sections(self, report: Report, text: str) -> None:
        ReportSection.objects.filter(report=report).delete()
        ordinal = 0
        current_name = "BODY"
        buffer: list[str] = []

        def flush() -> None:
            nonlocal ordinal
            if buffer:
                ReportSection.objects.create(
                    report=report, name=current_name[:120], ordinal=ordinal,
                    raw_text="\n".join(buffer).strip(), detection_confidence=0.8,
                )
                ordinal += 1

        for line in text.splitlines():
            stripped = line.strip()
            if _HEADING_RE.match(stripped):
                flush()
                current_name = stripped
                buffer = []
            else:
                buffer.append(line)
        flush()

    def _materialize_tests(self, report: Report, extraction, schema) -> list[ReportTest]:
        ReportTest.objects.filter(report=report).delete()
        alias_map = (schema.definition.get("aliases", {}) if schema else {})
        section = ReportSection.objects.filter(report=report).first()
        rows: list[ReportTest] = []
        for ev in extraction.values:
            canonical = alias_map.get(ev.analyte, ev.analyte)
            row = ReportTest(
                report=report,
                section=section,
                name=canonical,
                value_raw=ev.value_text[:120],
                unit_raw=ev.unit,
                state=ClinicalDataState.PENDING,
                extraction_method=ExtractionMethod.OCR,
                entity_confidence=_dec(ev.entity_confidence),
                context_confidence=_dec(ev.context_confidence),
                ocr_confidence=_dec(0.95),
            )
            if ev.value_number is not None and ev.unit:
                try:
                    conv = convert(ev.value_number, ev.unit, canonical)
                    row.value_normalized = conv.normalized_value
                    row.unit_normalized = conv.normalized_unit
                    row.conversion_rule_version = conv.rule_version
                except Exception:  # noqa: BLE001 - unknown analyte/unit: leave raw, flag later
                    row.state = ClinicalDataState.AMBIGUOUS
            elif ev.value_number is not None:
                row.value_normalized = ev.value_number
            rows.append(row)
        ReportTest.objects.bulk_create(rows)
        return list(ReportTest.objects.filter(report=report))

    def _extract_temporal(self, report: Report, text: str) -> None:
        for line in text.splitlines():
            low = line.lower()
            for attr, labels in _DATE_LABELS.items():
                if getattr(report, attr) is not None:
                    continue
                if any(lbl in low for lbl in labels):
                    m = _DATE_RE.search(line)
                    if m:
                        parsed = _parse_dt(m.group(1))
                        if parsed:
                            setattr(report, attr, parsed)

    def _validate(self, tests: list[ReportTest], schema) -> None:
        rules = schema.definition.get("validation_rules", {}) if schema else {}
        for t in tests:
            if t.state == ClinicalDataState.AMBIGUOUS or t.value_normalized is None:
                t.state = ClinicalDataState.AMBIGUOUS
                t.validation_status = ValidationStatus.REVIEW_REQUIRED
                t.save(update_fields=["state", "validation_status", "updated_at"])
                continue
            rule = rules.get(t.name, {})
            lo, hi = rule.get("min"), rule.get("max")
            value = t.value_normalized
            in_range = (lo is None or value >= _dec(lo)) and (hi is None or value <= _dec(hi))
            if in_range:
                t.state = ClinicalDataState.OBSERVED
                t.validation_status = ValidationStatus.PASSED
            else:
                t.state = ClinicalDataState.INVALID
                t.validation_status = ValidationStatus.FAILED
            t.save(update_fields=["state", "validation_status", "updated_at"])

    def _write_provenance(self, report: Report, tests: list[ReportTest]) -> None:
        for t in tests:
            prov = Provenance.objects.create(
                patient=report.patient,
                source_report=report,
                source_section=t.section.name if t.section else "",
                original_text=t.value_raw,
                extraction_method=t.extraction_method,
                extraction_confidence=min(
                    x for x in (t.entity_confidence, t.context_confidence, t.ocr_confidence) if x is not None
                )
                if any(x is not None for x in (t.entity_confidence, t.context_confidence))
                else None,
                validation_status=t.validation_status,
                original_value=t.value_raw,
                normalized_value=str(t.value_normalized) if t.value_normalized is not None else "",
                original_unit=t.unit_raw,
                normalized_unit=t.unit_normalized,
                conversion_rule_version=t.conversion_rule_version,
                observed_at=report.collected_at,
            )
            t.provenance = prov
            t.save(update_fields=["provenance", "updated_at"])

    def _values_by_field(self, tests: list[ReportTest]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for t in tests:
            out.setdefault(t.name, []).append(
                {"value": t.value_normalized, "unit": t.unit_normalized, "state": t.state}
            )
        return out

    def _reconcile(self, report: Report, tests: list[ReportTest]) -> list:
        """Compare finalized values against the most recent prior value for the
        same analyte. Material conflict -> preserve both + reconciliation event."""
        events = []

        # Duplicate-report detection (spec sections 19, 20): same patient, type
        # and collection time as an already-processed report.
        if report.report_class and report.collected_at:
            dup = (
                Report.objects.filter(
                    patient=report.patient,
                    report_class=report.report_class,
                    collected_at=report.collected_at,
                    processing_state=ReportProcessingState.FINALIZED,
                )
                .exclude(pk=report.pk)
                .first()
            )
            if dup is not None:
                events.append(
                    self.reconciliation.open_event(
                        patient=report.patient,
                        kind="DUPLICATE_REPORT",
                        summary=f"Possible duplicate of report {dup.public_id}",
                        detected_by_workflow="report_pipeline",
                        items=[
                            {"resource_type": "Report", "resource_id": dup.public_id,
                             "role_in_conflict": "existing", "snapshot": {}},
                            {"resource_type": "Report", "resource_id": report.public_id,
                             "role_in_conflict": "incoming", "snapshot": {}},
                        ],
                    )
                )

        for t in tests:
            if t.validation_status != ValidationStatus.PASSED or t.value_normalized is None:
                continue
            prior = (
                ReportTest.objects.filter(
                    report__patient=report.patient,
                    name=t.name,
                    validation_status=ValidationStatus.PASSED,
                    value_normalized__isnull=False,
                )
                .exclude(report=report)
                .order_by("-report__collected_at", "-created_at")
                .first()
            )
            if prior is None or prior.value_normalized is None:
                continue
            same_day = (
                report.collected_at
                and prior.report.collected_at
                and report.collected_at.date() == prior.report.collected_at.date()
            )
            unit_conflict = bool(
                t.unit_normalized and prior.unit_normalized and t.unit_normalized != prior.unit_normalized
            )
            value_conflict = same_day and t.value_normalized != prior.value_normalized
            if unit_conflict or value_conflict:
                events.append(
                    self.reconciliation.open_event(
                        patient=report.patient,
                        kind="UNIT_CONFLICT" if unit_conflict else "SAME_DAY_CONFLICT",
                        summary=f"{t.name}: incoming report conflicts with a prior value",
                        detected_by_workflow="report_pipeline",
                        items=[
                            {"resource_type": "ReportTest", "resource_id": prior.public_id,
                             "role_in_conflict": "existing",
                             "snapshot": {"value": str(prior.value_normalized), "unit": prior.unit_normalized}},
                            {"resource_type": "ReportTest", "resource_id": t.public_id,
                             "role_in_conflict": "incoming",
                             "snapshot": {"value": str(t.value_normalized), "unit": t.unit_normalized}},
                        ],
                    )
                )
        return events

    def _review_reason(self, comparison, conflicts, tests) -> str:
        if conflicts:
            return "Conflicting clinical values were found; reconciliation required."
        if comparison is None:
            return "No active schema for this report type; manual structuring required."
        if comparison.status == CompletenessStatus.INVALID:
            return f"Values outside plausible range: {', '.join(comparison.invalid)}."
        if comparison.status == CompletenessStatus.INCOMPLETE:
            return f"Missing required fields: {', '.join(comparison.missing_required)}."
        if any(t.validation_status != ValidationStatus.PASSED for t in tests):
            return "One or more extracted values could not be validated."
        return "Human review required before finalization."

    def _second_opinion(self, report: Report) -> second_reader.SecondOpinion:
        """Ask the document service what it made of the same file.

        Never raises and never blocks: a second reader that can make a report
        unprocessable is not a second reader, it is a new dependency. Every
        failure - service down, timeout, missing credential - is "no opinion",
        and the pipeline continues exactly as it would have.
        """
        if second_reader.mode() == second_reader.OFF:
            return second_reader.SecondOpinion()
        try:
            content = read_report_bytes(report)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            return second_reader.SecondOpinion(
                consulted=True, available=False,
                unavailable_reason=f"could not read the stored file: {exc}"[:200],
            )
        return second_reader.consult(report, content)

    def _review(
        self,
        report: Report,
        reason: str,
        *,
        report_class: str | None = None,
        second_opinion: second_reader.SecondOpinion | None = None,
    ) -> ServiceResult:
        report.processing_state = ReportProcessingState.REVIEW_REQUIRED
        report.validation_status = ValidationStatus.REVIEW_REQUIRED
        report.review_reason = reason[:255]
        report.save()
        metadata = {
            "outcome": "REVIEW_REQUIRED",
            "report_class": report_class or report.report_class,
        }
        if second_opinion is not None:
            metadata["second_reader"] = second_opinion.as_audit_metadata()
        audit_service.record(
            audit.REPORT_PROCESSED, resource=report, metadata=metadata,
        )
        return ServiceResult.blocked(
            "REVIEW_REQUIRED", reason, value=PipelineResult(report, report.processing_state, reason)
        )


def _dec(value) -> object:
    from decimal import Decimal

    return Decimal(str(value))


def _parse_dt(token: str) -> dt.datetime | None:
    token = token.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            naive = dt.datetime.strptime(token, fmt)
            return timezone.make_aware(naive) if timezone.is_naive(naive) else naive
        except ValueError:
            continue
    return None
