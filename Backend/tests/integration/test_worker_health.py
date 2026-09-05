"""A dead worker must be loud.

The failure this guards against is not a crash, it is a silence: the queue is a
database table, so when the worker stops the API carries on returning 201 for
every upload and the reports simply never process. Nothing raises, so nothing
alerts. These tests assert that the condition is detectable from outside.
"""
from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.common.enums import JobState
from apps.jobs.health import (
    BACKLOG_AGE_SECONDS,
    STALE_AFTER_SECONDS,
    beat,
    queue_status,
)
from apps.jobs.models import Job, WorkerHeartbeat

pytestmark = pytest.mark.django_db


def _queue_job(*, age_seconds: int = 0, state: str = JobState.QUEUED) -> Job:
    moment = timezone.now() - dt.timedelta(seconds=age_seconds)
    return Job.objects.create(
        job_type="reports.process",
        payload={"report_id": "00000000-0000-0000-0000-000000000000"},
        state=state,
        available_at=moment,
    )


# --- the silent stall ----------------------------------------------------
def test_work_waiting_with_no_live_worker_is_reported_as_down():
    _queue_job()
    status = queue_status()
    assert status["status"] == "down"
    assert status["queued"] == 1
    assert status["workers_alive"] == 0
    assert any("not being processed" in p for p in status["problems"])
    assert any("run_worker" in p for p in status["problems"]), (
        "the operator should be told how to fix it, not just that it is broken"
    )


def test_a_worker_that_stopped_beating_is_not_counted_as_alive():
    beat("worker-gone")
    WorkerHeartbeat.objects.filter(worker_id="worker-gone").update(
        last_beat_at=timezone.now() - dt.timedelta(seconds=STALE_AFTER_SECONDS + 30)
    )
    _queue_job()

    status = queue_status()
    assert status["status"] == "down"
    assert status["workers_alive"] == 0
    assert status["workers_known"] == 1, "we should still know it once existed"


def test_an_environment_that_never_started_a_worker_says_so():
    status = queue_status()
    assert status["status"] == "degraded"
    assert any("has ever reported" in p for p in status["problems"])


# --- healthy ------------------------------------------------------------
def test_a_live_worker_with_an_empty_queue_is_ok():
    beat("worker-1")
    status = queue_status()
    assert status["status"] == "ok"
    assert status["workers_alive"] == 1
    assert status["problems"] == []


def test_a_live_worker_with_fresh_work_is_still_ok():
    """A job queued a moment ago is normal operation, not a backlog."""
    beat("worker-1")
    _queue_job()
    status = queue_status()
    assert status["status"] == "ok"
    assert status["queued"] == 1


# --- degraded -----------------------------------------------------------
def test_a_backlog_despite_a_live_worker_is_degraded():
    beat("worker-1")
    _queue_job(age_seconds=BACKLOG_AGE_SECONDS + 60)
    status = queue_status()
    assert status["status"] == "degraded"
    assert status["stale_queued"] == 1


def test_jobs_that_exhausted_their_retries_are_surfaced():
    beat("worker-1")
    _queue_job(state=JobState.FAILED)
    status = queue_status()
    assert status["status"] == "degraded"
    assert status["failed"] == 1
    assert any("retries" in p for p in status["problems"])


def test_the_oldest_queued_age_is_reported():
    beat("worker-1")
    _queue_job(age_seconds=120)
    assert queue_status()["oldest_queued_age_seconds"] >= 119


# --- heartbeats ---------------------------------------------------------
def test_a_heartbeat_updates_in_place_rather_than_accumulating():
    beat("worker-1")
    beat("worker-1")
    beat("worker-1")
    assert WorkerHeartbeat.objects.filter(worker_id="worker-1").count() == 1


def test_the_worker_command_beats_even_when_there_is_no_work():
    """A worker polling an empty queue is healthy and must prove it."""
    from django.core.management import call_command

    call_command("run_worker", "--once")
    assert WorkerHeartbeat.objects.exists()
    assert queue_status()["workers_alive"] == 1


# --- the endpoint -------------------------------------------------------
def test_readyz_returns_503_when_the_pipeline_is_stalled(api_client):
    _queue_job()
    resp = api_client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"
    assert resp.json()["checks"]["jobs"]["status"] == "down"


def test_readyz_returns_200_when_healthy(api_client):
    beat("worker-1")
    resp = api_client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["checks"]["database"]["status"] == "ok"


def test_readyz_needs_no_credentials_and_leaks_no_patient_data(api_client):
    """A probe endpoint is effectively public, so it must be dull."""
    beat("worker-1")
    body = api_client.get("/readyz").json()
    flat = str(body).lower()
    for leak in ("mrn", "given_name", "email", "patient_id", "password"):
        assert leak not in flat


def test_healthz_stays_a_pure_liveness_check(api_client):
    """It must not start failing because a *dependency* is down.

    Orchestrators restart a container that fails its liveness probe. Wiring a
    database check in here would turn a database outage into a restart loop.
    """
    _queue_job()
    resp = api_client.get("/healthz")
    assert resp.status_code == 200
