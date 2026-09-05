"""Guardrails for results a person reads without a clinician present."""
from __future__ import annotations

import datetime as pydt
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.common.enums import Role
from apps.risk.models import RiskAssessment
from apps.risk.safety import urgent_care_notice

pytestmark = pytest.mark.django_db


def _completed(patient, user, *, score: str, task: str = "cvd", age_minutes: int = 0):
    row = RiskAssessment.objects.create(
        patient=patient,
        requested_by=user,
        task=task,
        status=RiskAssessment.Status.COMPLETED,
        outcome_code="OK",
        calibrated_score=Decimal(score),
        input_snapshot={},
    )
    if age_minutes:
        # created_at is auto_now_add, so move it explicitly.
        RiskAssessment.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - pydt.timedelta(minutes=age_minutes)
        )
        row.refresh_from_db()
    return row


# --- urgent-symptom guidance ------------------------------------------
def test_elevated_band_carries_urgent_symptom_guidance():
    notice = urgent_care_notice(Decimal("0.80"))
    assert notice is not None
    assert notice["level"] == "URGENT_SYMPTOMS"
    # It must tell the reader the estimate says nothing about *today*.
    assert "cannot tell you whether something is wrong today" in notice["detail"]


def test_low_band_carries_no_urgent_guidance():
    assert urgent_care_notice(Decimal("0.10")) is None
    assert urgent_care_notice(None) is None


def test_patient_reading_an_elevated_result_sees_the_notice(
    auth_client, make_user, make_patient
):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    assessment = _completed(patient, alice, score="0.82")

    resp = auth_client(alice).get(f"/api/v1/risk/assessments/{assessment.public_id}/")
    assert resp.status_code == 200
    assert resp.data["safety_notice"]["level"] == "URGENT_SYMPTOMS"


def test_a_blocked_result_carries_no_notice(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    blocked = RiskAssessment.objects.create(
        patient=patient, requested_by=alice, task="cvd",
        status=RiskAssessment.Status.BLOCKED, outcome_code="INSUFFICIENT_DATA",
        input_snapshot={},
    )
    resp = auth_client(alice).get(f"/api/v1/risk/assessments/{blocked.public_id}/")
    assert resp.data["safety_notice"] is None


# --- self-service pacing ----------------------------------------------
@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 60, "DAILY_CAP": 5})
def test_rerunning_straight_after_a_scored_result_is_paced(
    auth_client, make_user, make_patient
):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    _completed(patient, alice, score="0.40")

    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code == 429
    assert resp.data["error"]["code"] == "ANALYSIS_COOLDOWN"
    # The client must be able to say when, not just "no".
    assert resp.data["error"]["details"]["retry_after_seconds"] > 0


@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 60, "DAILY_CAP": 5})
def test_cooldown_expires(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    _completed(patient, alice, score="0.40", age_minutes=90)

    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code != 429


@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 60, "DAILY_CAP": 5})
def test_a_blocked_attempt_does_not_start_a_cooldown(auth_client, make_user, make_patient):
    """Being told data is missing then made to wait an hour would be perverse."""
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    RiskAssessment.objects.create(
        patient=patient, requested_by=alice, task="cvd",
        status=RiskAssessment.Status.BLOCKED, outcome_code="INSUFFICIENT_DATA",
        input_snapshot={},
    )
    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code != 429


@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 0, "DAILY_CAP": 2})
def test_daily_cap_counts_blocked_attempts_too(auth_client, make_user, make_patient):
    alice = make_user(Role.PATIENT)
    patient = make_patient(user=alice)
    for _ in range(2):
        RiskAssessment.objects.create(
            patient=patient, requested_by=alice, task="cvd",
            status=RiskAssessment.Status.BLOCKED, outcome_code="INSUFFICIENT_DATA",
            input_snapshot={},
        )
    resp = auth_client(alice).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code == 429
    assert resp.data["error"]["details"]["limit"] == 2


@override_settings(SELF_SERVICE_ANALYSIS={"COOLDOWN_MINUTES": 60, "DAILY_CAP": 1})
def test_a_clinicians_caseload_is_not_paced(
    auth_client, make_doctor, make_patient, assign_patient
):
    """The limits exist for self-service, not for someone working a list."""
    doctor = make_doctor()
    patient = make_patient()
    assign_patient(doctor, patient)
    _completed(patient, doctor.user, score="0.40")

    resp = auth_client(doctor.user).post(
        "/api/v1/risk/assessments/",
        {"patient_id": str(patient.public_id), "task": "cvd"},
        format="json",
    )
    assert resp.status_code != 429
