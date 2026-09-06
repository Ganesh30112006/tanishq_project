"""Chronological health timeline for a patient (spec sections 21, 42).

Composes events the caller is already authorized to see - completed risk
assessments, finalized/review-required reports, clinical notes, and alerts -
into one time-ordered feed. This performs no new authorization decision of
its own; the caller has already resolved and authorized the patient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.common.display import display_number, display_term


@dataclass(slots=True)
class TimelineEvent:
    id: str
    title: str
    detail: str
    occurred_at: datetime
    type: str  # assessment | report | measurement | note | alert


def _risk_events(patient, *, show_scores: bool) -> list[TimelineEvent]:
    from apps.risk.interpretation import interpret
    from apps.risk.models import RiskAssessment

    events = []
    for row in (
        RiskAssessment.objects.filter(patient=patient, status=RiskAssessment.Status.COMPLETED)
        .exclude(calibrated_score__isnull=True)
        .select_related("model_version")
        .order_by("-created_at")[:15]
    ):
        model = f"{row.model_version.model_id}:{row.model_version.version}" if row.model_version_id else row.task
        # The timeline must not restate a figure the governed reading withheld -
        # a number kept off the result page is no less misleading here.
        reading = interpret(row, for_clinician=show_scores)
        if reading and reading.get("show_score"):
            summary = f"Calibrated score {reading['score_percent']}/100"
        else:
            summary = (reading or {}).get("band_label") or "Estimate recorded"
        # The model identifier is provenance for a clinician and noise for a
        # patient, who has the same information on the result itself.
        detail = f"{summary} ({model})" if show_scores else summary
        events.append(
            TimelineEvent(
                id=str(row.public_id),
                title=f"{display_term(row.task)} risk assessment",
                detail=detail,
                occurred_at=row.created_at,
                type="assessment",
            )
        )
    return events


def _report_events(patient) -> list[TimelineEvent]:
    from apps.common.enums import ReportProcessingState
    from apps.reports.models import Report

    events = []
    for row in (
        Report.objects.filter(
            patient=patient,
            processing_state__in=(
                ReportProcessingState.FINALIZED,
                ReportProcessingState.REVIEW_REQUIRED,
            ),
        )
        .order_by("-created_at")[:15]
    ):
        label = (row.report_class or "Report").replace("_", " ").title()
        detail = (
            "Requires human review before use." if row.processing_state == ReportProcessingState.REVIEW_REQUIRED
            else f"Finalized · completeness {row.completeness_status or 'UNKNOWN'}"
        )
        events.append(
            TimelineEvent(
                id=str(row.public_id),
                title=f"{label} report",
                detail=detail,
                occurred_at=row.created_at,
                type="report",
            )
        )
    return events


def _measurement_events(patient) -> list[TimelineEvent]:
    from apps.common.enums import TRUSTWORTHY_CLINICAL_STATES
    from apps.health.models import HealthMeasurement, MeasurementKind

    events = []
    for row in (
        HealthMeasurement.objects.filter(patient=patient, state__in=TRUSTWORTHY_CLINICAL_STATES)
        .order_by("-observed_at")[:10]
    ):
        label = MeasurementKind(row.kind).label
        value = f"{display_number(row.value_num)} {row.unit}".strip() if row.value_num is not None else "recorded"
        events.append(
            TimelineEvent(
                id=str(row.pk),
                title=label,
                detail=value,
                occurred_at=row.observed_at,
                type="measurement",
            )
        )
    return events


def _note_events(patient) -> list[TimelineEvent]:
    from apps.medical_records.models import ClinicalNote

    events = []
    for row in (
        ClinicalNote.objects.filter(patient=patient)
        .select_related("author")
        .order_by("-authored_at")[:10]
    ):
        author = row.author.full_name or row.author.email if row.author_id else "Care team"
        events.append(
            TimelineEvent(
                id=str(row.public_id),
                title=f"{row.get_note_type_display()} by {author}",
                detail=row.body[:200],
                occurred_at=row.authored_at,
                type="note",
            )
        )
    return events


def _alert_events(patient) -> list[TimelineEvent]:
    from apps.alerts.models import Alert

    events = []
    for row in Alert.objects.filter(patient=patient).order_by("-created_at")[:15]:
        events.append(
            TimelineEvent(
                id=str(row.public_id),
                title=row.title,
                detail=row.detail or row.category.replace("_", " ").title(),
                occurred_at=row.created_at,
                type="alert",
            )
        )
    return events


def build_timeline(patient, *, limit: int = 8, show_scores: bool = False) -> list[TimelineEvent]:
    """``show_scores`` mirrors the risk card: only a clinician sees the figure."""
    events = [
        *_risk_events(patient, show_scores=show_scores),
        *_report_events(patient),
        *_measurement_events(patient),
        *_note_events(patient),
        *_alert_events(patient),
    ]
    events.sort(key=lambda event: event.occurred_at, reverse=True)
    return events[:limit]
