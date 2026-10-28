"""Role-aware dashboard composition (spec section 2: Django owns business /
workflow state and composes it into the client-facing view; FastAPI never
sees this).

The summary shown is always derived from the *authenticated user's own real
roles* - never a client-supplied role (spec sections 5, 7, 54). A caller may
optionally name one of their own roles to switch which of their views they
see (useful for a user who genuinely holds more than one role); any other
value is ignored and the highest-precedence real role is used instead.

Every query here reuses the same authorization-scoped querysets the rest of
the API uses (``visible_patient_queryset``, etc.) - the dashboard never has
its own, wider view of the data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db.models import OuterRef, Subquery

from apps.common.display import display_term
from apps.common.enums import (
    JobState,
    MissingDataTaskStatus,
    ReconciliationStatus,
    Role,
    ValidationStatus,
)

# Highest-precedence role first: an admin who also holds a doctor role still
# sees the admin view unless they explicitly ask for another of their roles.
_ROLE_PRECEDENCE = [Role.ADMIN, Role.DOCTOR, Role.LAB_TECHNICIAN, Role.PATIENT]

_OPEN_TASK_STATUSES = (
    MissingDataTaskStatus.MISSING,
    MissingDataTaskStatus.NOTIFIED,
    MissingDataTaskStatus.ACKNOWLEDGED,
    MissingDataTaskStatus.IN_PROGRESS,
)

_IN_PROGRESS_REPORT_STATES = (
    "RECEIVED", "VALIDATING_FILE", "EXTRACTING", "CLASSIFYING", "STRUCTURING", "RECONCILING",
)


@dataclass(slots=True)
class Metric:
    label: str
    value: str
    context: str
    tone: str  # neutral | positive | warning | critical


@dataclass(slots=True)
class ActivityItem:
    id: str
    title: str
    detail: str
    timestamp: datetime
    type: str  # risk | report | note | measurement | alert


@dataclass(slots=True)
class DashboardSummary:
    role: str
    greeting: str
    metrics: list[Metric]
    recent_activity: list[ActivityItem]


def _high_risk_floor() -> float:
    """The probability above which a patient's latest score is displayed as
    HIGH or CRITICAL, taken from the configured display bands rather than a
    number repeated in two places."""
    bands = sorted(settings.RISK_DISPLAY_BANDS, key=lambda b: b["max_probability"])
    for band in bands:
        if band["code"] == "MEDIUM":
            return float(band["max_probability"])
    return 0.5


def effective_role(user, requested: str | None = None) -> str:
    roles = user.role_codes
    if requested and requested in roles:
        return requested
    for role in _ROLE_PRECEDENCE:
        if role in roles:
            return role
    return next(iter(roles), Role.PATIENT)


class DashboardService:
    def summary(self, user, *, requested_role: str | None = None) -> DashboardSummary:
        role = effective_role(user, requested_role)
        greeting = f"Good to see you, {user.full_name or user.email.split('@')[0]}"
        if role == Role.PATIENT:
            metrics, activity = self._patient_view(user)
        elif role == Role.DOCTOR:
            metrics, activity = self._doctor_view(user)
        elif role == Role.LAB_TECHNICIAN:
            metrics, activity = self._lab_view(user)
        elif role == Role.ADMIN:
            metrics, activity = self._admin_view(user)
        else:
            metrics, activity = [], []
        return DashboardSummary(role=role, greeting=greeting, metrics=metrics, recent_activity=activity)

    # -- PATIENT ----------------------------------------------------------
    def _patient_view(self, user) -> tuple[list[Metric], list[ActivityItem]]:
        from apps.authz.relationships import patient_for_user
        from apps.patients.presentation import build_card_context
        from apps.patients.timeline import build_timeline

        patient = patient_for_user(user)
        if patient is None:
            return [], []

        ctx = build_card_context(patient)
        risk = ctx.risk
        # "Stable" is a judgement, and with no estimate and no alert nothing
        # has been judged. A new record must not open on reassurance.
        unchecked = ctx.status == "STABLE" and risk.level is None
        metrics = [
            Metric(
                label="Current risk",
                value=f"{risk.score}/100" if risk.score is not None else "Not assessed",
                context=risk.level or "No completed assessment yet",
                tone="critical" if risk.level in ("HIGH", "CRITICAL") else "warning" if risk.level == "MEDIUM" else "positive" if risk.level else "neutral",
            ),
            Metric(
                label="Record status",
                value="Not checked yet" if unchecked else ctx.status.replace("_", " ").title(),
                context=(
                    "Upload a report or run the analysis so there is something to check"
                    if unchecked else "Based on your open alerts and current risk"
                ),
                tone="neutral" if unchecked else "critical" if ctx.status == "REVIEW_REQUIRED" else "warning" if ctx.status == "MONITORING" else "positive",
            ),
        ]
        from apps.alerts.models import Alert

        open_alerts = Alert.objects.filter(patient=patient, status=Alert.Status.OPEN).count()
        metrics.append(Metric(
            label="Open alerts", value=str(open_alerts),
            context="Unresolved alerts on your record",
            tone="warning" if open_alerts else "neutral",
        ))

        events = build_timeline(patient, limit=8)
        activity = [_timeline_to_activity(event) for event in events]
        return metrics, activity

    # -- DOCTOR -------------------------------------------------------------
    def _doctor_view(self, user) -> tuple[list[Metric], list[ActivityItem]]:
        from apps.alerts.models import Alert
        from apps.authz.relationships import visible_patient_queryset
        from apps.notifications.models import MissingDataTask
        from apps.risk.models import RiskAssessment

        patient_ids = list(visible_patient_queryset(user).values_list("pk", flat=True))
        total = len(patient_ids)

        latest_score = (
            RiskAssessment.objects.filter(
                patient=OuterRef("pk"),
                status=RiskAssessment.Status.COMPLETED,
                calibrated_score__isnull=False,
            )
            .order_by("-created_at")
            .values("calibrated_score")[:1]
        )
        from apps.patients.models import Patient

        high_risk = (
            Patient.objects.filter(pk__in=patient_ids)
            .annotate(latest_score=Subquery(latest_score))
            .filter(latest_score__gt=_high_risk_floor())
            .count()
        )
        open_alerts = Alert.objects.filter(patient_id__in=patient_ids, status=Alert.Status.OPEN).count()
        missing_data = MissingDataTask.objects.filter(
            patient_id__in=patient_ids, assigned_role=Role.DOCTOR, status__in=_OPEN_TASK_STATUSES
        ).count()

        metrics = [
            Metric(label="Assigned patients", value=str(total), context="Active assignments", tone="neutral"),
            Metric(
                label="High risk", value=str(high_risk),
                context="Patients above the high-risk threshold",
                tone="critical" if high_risk else "positive",
            ),
            Metric(
                label="Open alerts", value=str(open_alerts),
                context="Across your assigned patients",
                tone="warning" if open_alerts else "neutral",
            ),
            Metric(
                label="Missing-data tasks", value=str(missing_data),
                context="Blocking a risk assessment or review",
                tone="warning" if missing_data else "positive",
            ),
        ]
        activity = self._cross_patient_activity(patient_ids, limit=8)
        return metrics, activity

    # -- LAB_TECHNICIAN -------------------------------------------------
    def _lab_view(self, user) -> tuple[list[Metric], list[ActivityItem]]:
        from apps.laboratories.models import LabOrder, LabResult, LabTechnician
        from apps.notifications.models import MissingDataTask

        lab_ids = list(
            LabTechnician.objects.filter(user_id=user.pk, is_active=True).values_list(
                "laboratory_id", flat=True
            )
        )
        open_orders = LabOrder.objects.filter(
            laboratory_id__in=lab_ids, status__in=LabOrder.OPEN_STATUSES
        ).count()
        awaiting_validation = (
            LabResult.objects.filter(order__laboratory_id__in=lab_ids, superseded_by__isnull=True)
            .exclude(validations__status=ValidationStatus.PASSED)
            .distinct()
            .count()
        )
        patient_ids = LabOrder.objects.filter(
            laboratory_id__in=lab_ids, status__in=LabOrder.OPEN_STATUSES
        ).values_list("patient_id", flat=True)
        missing_data = MissingDataTask.objects.filter(
            assigned_role=Role.LAB_TECHNICIAN, patient_id__in=patient_ids, status__in=_OPEN_TASK_STATUSES
        ).count()

        metrics = [
            Metric(label="Open orders", value=str(open_orders), context="Across your laboratories", tone="neutral"),
            Metric(
                label="Awaiting validation", value=str(awaiting_validation),
                context="Results without a passed validation",
                tone="warning" if awaiting_validation else "positive",
            ),
            Metric(
                label="Missing-data tasks", value=str(missing_data),
                context="Routed to the laboratory",
                tone="warning" if missing_data else "positive",
            ),
        ]
        activity = self._lab_activity(lab_ids, limit=8)
        return metrics, activity

    # -- ADMIN ------------------------------------------------------------
    def _admin_view(self, user) -> tuple[list[Metric], list[ActivityItem]]:
        from apps.accounts.models import User
        from apps.jobs.models import Job
        from apps.patients.models import PatientIdentityCandidate
        from apps.reconciliation.models import ReconciliationEvent

        active_users = User.objects.filter(is_active=True).count()
        open_reconciliation = ReconciliationEvent.objects.filter(status=ReconciliationStatus.OPEN).count()
        pending_identity = PatientIdentityCandidate.objects.filter(
            status=PatientIdentityCandidate.Status.PENDING
        ).count()
        failed_jobs = Job.objects.filter(state=JobState.FAILED).count()

        metrics = [
            Metric(label="Active users", value=str(active_users), context="Across all roles", tone="neutral"),
            Metric(
                label="Reconciliation events", value=str(open_reconciliation),
                context="Open, awaiting review", tone="warning" if open_reconciliation else "positive",
            ),
            Metric(
                label="Identity candidates", value=str(pending_identity),
                context="Pending duplicate-patient review", tone="warning" if pending_identity else "positive",
            ),
            Metric(
                label="Failed jobs", value=str(failed_jobs),
                context="Background jobs needing attention", tone="critical" if failed_jobs else "positive",
            ),
        ]
        activity = self._audit_activity(limit=8)
        return metrics, activity

    # -- shared activity builders ----------------------------------------
    def _cross_patient_activity(self, patient_ids: list[int], *, limit: int) -> list[ActivityItem]:
        from apps.alerts.models import Alert
        from apps.reports.models import Report
        from apps.risk.models import RiskAssessment

        items: list[ActivityItem] = []
        for row in (
            RiskAssessment.objects.filter(patient_id__in=patient_ids, status=RiskAssessment.Status.COMPLETED)
            .exclude(calibrated_score__isnull=True)
            .select_related("patient")
            .order_by("-created_at")[:limit]
        ):
            items.append(ActivityItem(
                id=str(row.public_id),
                title=f"Risk assessment · {row.patient.full_name}",
                detail=f"{display_term(row.task)} scored {round(float(row.calibrated_score) * 100)}/100",
                timestamp=row.created_at, type="risk",
            ))
        for row in (
            Report.objects.filter(patient_id__in=patient_ids).select_related("patient").order_by("-created_at")[:limit]
        ):
            items.append(ActivityItem(
                id=str(row.public_id),
                title=f"Report · {row.patient.full_name}",
                detail=f"{(row.report_class or 'Unclassified').title()} - {row.processing_state.replace('_', ' ').title()}",
                timestamp=row.created_at, type="report",
            ))
        for row in (
            Alert.objects.filter(patient_id__in=patient_ids).select_related("patient").order_by("-created_at")[:limit]
        ):
            items.append(ActivityItem(
                id=str(row.public_id), title=f"{row.title} · {row.patient.full_name}",
                detail=row.detail or row.category.replace("_", " ").title(),
                timestamp=row.created_at, type="alert",
            ))
        items.sort(key=lambda item: item.timestamp, reverse=True)
        return items[:limit]

    def _lab_activity(self, lab_ids: list, *, limit: int) -> list[ActivityItem]:
        from apps.laboratories.models import LabOrder, LabResult

        items: list[ActivityItem] = []
        for row in (
            LabOrder.objects.filter(laboratory_id__in=lab_ids)
            .select_related("patient")
            .order_by("-requested_at")[:limit]
        ):
            items.append(ActivityItem(
                id=str(row.public_id), title=f"Order · {row.patient.full_name}",
                detail=f"{row.panel} - {row.get_status_display()}",
                timestamp=row.requested_at, type="report",
            ))
        for row in (
            LabResult.objects.filter(order__laboratory_id__in=lab_ids)
            .select_related("order__patient")
            .order_by("-recorded_at")[:limit]
        ):
            items.append(ActivityItem(
                id=str(row.public_id), title=f"Result · {row.order.patient.full_name}",
                detail=f"{row.analyte} recorded", timestamp=row.recorded_at, type="measurement",
            ))
        items.sort(key=lambda item: item.timestamp, reverse=True)
        return items[:limit]

    def _audit_activity(self, *, limit: int) -> list[ActivityItem]:
        from apps.audit.models import AuditLog

        items = []
        for row in AuditLog.objects.order_by("-created_at")[:limit]:
            actor = row.actor_label or (row.actor.email if row.actor_id else "system")
            items.append(ActivityItem(
                id=str(row.public_id), title=row.action.replace(".", " ").replace("_", " ").title(),
                detail=f"{actor} · {row.result}", timestamp=row.created_at, type="note",
            ))
        return items


_TIMELINE_TYPE_MAP = {"assessment": "risk", "report": "report", "measurement": "measurement", "note": "note", "alert": "alert"}


def _timeline_to_activity(event) -> ActivityItem:
    return ActivityItem(
        id=event.id, title=event.title, detail=event.detail,
        timestamp=event.occurred_at, type=_TIMELINE_TYPE_MAP.get(event.type, "note"),
    )
