"""Computed, presentation-facing fields for patient list/detail views.

These are display convenience values (initials, a risk band, a workflow
status) derived from data Django already authorized the caller to see - never
new clinical facts, never written back to the record. Keeping the derivation
here (rather than inline in a serializer or, worse, a signal) makes it a
single explicit and testable place, per spec sections 55-56.

A risk *band* (LOW/MEDIUM/HIGH/CRITICAL) is a presentation cut over a
calibrated probability, configured in ``settings.RISK_DISPLAY_BANDS`` - it is
not a clinical grade and is only ever derived from a COMPLETED assessment
(spec section 27 - severity/priority comes from validated policy, not an
inferred medical judgement).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.utils import timezone


def initials(given_name: str, family_name: str) -> str:
    parts = [p[0] for p in (given_name, family_name) if p]
    return "".join(parts).upper()[:2] or "?"


def age_years(date_of_birth: dt.date | None, *, today: dt.date | None = None) -> int | None:
    if date_of_birth is None:
        return None
    today = today or timezone.now().date()
    years = today.year - date_of_birth.year
    if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return years


def risk_band(probability: Decimal | float) -> str:
    value = float(probability)
    for band in settings.RISK_DISPLAY_BANDS:
        if value <= band["max_probability"]:
            return str(band["code"])
    return str(settings.RISK_DISPLAY_BANDS[-1]["code"])


@dataclass(slots=True)
class PatientRiskSummary:
    level: str | None
    score: int | None
    trend: str
    assessment: object | None


def latest_risk_summary(patient) -> PatientRiskSummary:
    from apps.risk.models import RiskAssessment

    rows = list(
        RiskAssessment.objects.filter(patient=patient, status=RiskAssessment.Status.COMPLETED)
        .exclude(calibrated_score__isnull=True)
        .order_by("-created_at")[:2]
    )
    if not rows:
        return PatientRiskSummary(level=None, score=None, trend="STABLE", assessment=None)
    latest = rows[0]
    score = round(float(latest.calibrated_score) * 100)
    trend = "STABLE"
    if len(rows) > 1 and rows[1].calibrated_score is not None:
        previous = round(float(rows[1].calibrated_score) * 100)
        if score > previous:
            trend = "UP"
        elif score < previous:
            trend = "DOWN"
    return PatientRiskSummary(
        level=risk_band(latest.calibrated_score), score=score, trend=trend, assessment=latest
    )


def latest_open_alert(patient):
    from apps.alerts.models import Alert

    return (
        Alert.objects.filter(patient=patient, status=Alert.Status.OPEN)
        .order_by("-created_at")
        .first()
    )


_HIGH_RISK_LEVELS = frozenset({"HIGH", "CRITICAL"})


def patient_status(risk: PatientRiskSummary, alert) -> str:
    """A workflow status - STABLE / MONITORING / REVIEW_REQUIRED - never a
    diagnosis. Derived from open alert severity and the current risk band."""
    from apps.alerts.models import Alert

    if alert is not None and alert.severity == Alert.Severity.HIGH:
        return "REVIEW_REQUIRED"
    if risk.level in _HIGH_RISK_LEVELS:
        return "REVIEW_REQUIRED"
    if alert is not None or risk.level == "MEDIUM":
        return "MONITORING"
    return "STABLE"


def last_updated_at(patient) -> dt.datetime | None:
    from apps.health.models import HealthMeasurement
    from apps.reports.models import Report
    from apps.risk.models import RiskAssessment

    candidates: list[dt.datetime] = [patient.updated_at]
    latest_risk = (
        RiskAssessment.objects.filter(patient=patient)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if latest_risk:
        candidates.append(latest_risk)
    latest_report = (
        Report.objects.filter(patient=patient)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if latest_report:
        candidates.append(latest_report)
    latest_measurement = (
        HealthMeasurement.objects.filter(patient=patient)
        .order_by("-observed_at")
        .values_list("observed_at", flat=True)
        .first()
    )
    if latest_measurement:
        candidates.append(latest_measurement)
    return max(candidates)


@dataclass(slots=True)
class PatientCardContext:
    """Everything the card/profile serializers need, computed once."""

    risk: PatientRiskSummary
    alert: object | None
    status: str
    last_updated: dt.datetime | None


def build_card_context(patient) -> PatientCardContext:
    risk = latest_risk_summary(patient)
    alert = latest_open_alert(patient)
    return PatientCardContext(
        risk=risk,
        alert=alert,
        status=patient_status(risk, alert),
        last_updated=last_updated_at(patient),
    )


# --------------------------------------------------------------------------
# List filtering (spec section 42: filtering/sorting on list endpoints)
# --------------------------------------------------------------------------
# ``risk``/``status`` are computed, not stored columns, so filtering the
# *list* endpoint on them has to happen in SQL (an annotated subquery) rather
# than by materializing every visible patient in Python - otherwise filtering
# and pagination would disagree with each other on a panel bigger than one
# page. This mirrors ``patient_status`` / ``risk_band`` above; the case
# boundaries come from the same ``settings.RISK_DISPLAY_BANDS``.
def filter_patients(queryset, *, risk: str | None = None, status: str | None = None, search: str | None = None):
    from django.db.models import Case, CharField, Exists, OuterRef, Q, Subquery, Value, When

    from apps.alerts.models import Alert
    from apps.risk.models import RiskAssessment

    if search:
        queryset = queryset.filter(
            Q(given_name__icontains=search) | Q(family_name__icontains=search) | Q(mrn__icontains=search)
        )

    if not risk and not status:
        return queryset

    latest_score_sq = (
        RiskAssessment.objects.filter(
            patient=OuterRef("pk"),
            status=RiskAssessment.Status.COMPLETED,
            calibrated_score__isnull=False,
        )
        .order_by("-created_at")
        .values("calibrated_score")[:1]
    )
    bands = sorted(settings.RISK_DISPLAY_BANDS, key=lambda b: b["max_probability"])
    band_whens = [
        When(_latest_score__lte=band["max_probability"], then=Value(band["code"])) for band in bands
    ]
    queryset = queryset.annotate(_latest_score=Subquery(latest_score_sq)).annotate(
        _risk_band=Case(*band_whens, default=Value(None), output_field=CharField(null=True))
    )

    if risk:
        queryset = queryset.filter(_risk_band=risk)

    if status:
        has_open_alert = Exists(Alert.objects.filter(patient=OuterRef("pk"), status=Alert.Status.OPEN))
        has_high_alert = Exists(
            Alert.objects.filter(
                patient=OuterRef("pk"), status=Alert.Status.OPEN, severity=Alert.Severity.HIGH
            )
        )
        queryset = queryset.annotate(_has_open_alert=has_open_alert, _has_high_alert=has_high_alert).annotate(
            _status=Case(
                When(Q(_has_high_alert=True) | Q(_risk_band__in=list(_HIGH_RISK_LEVELS)), then=Value("REVIEW_REQUIRED")),
                When(Q(_has_open_alert=True) | Q(_risk_band="MEDIUM"), then=Value("MONITORING")),
                default=Value("STABLE"),
                output_field=CharField(),
            )
        )
        queryset = queryset.filter(_status=status)

    return queryset
