"""Database-backed background jobs (spec section 47).

No Redis / broker. Workers poll with ``SELECT ... FOR UPDATE SKIP LOCKED`` so
multiple workers can run safely. Jobs are traceable, status-aware, retry-safe
and idempotent by key. Payloads carry only identifiers - a handler re-loads
and re-authorizes through the normal services.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.common.enums import JobState
from apps.common.models import TimeStampedModel, UUIDTimeStampedModel


class Job(UUIDTimeStampedModel):
    job_type = models.CharField(max_length=80, db_index=True)
    state = models.CharField(max_length=12, choices=JobState.choices, default=JobState.QUEUED)
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    priority = models.IntegerField(default=0, help_text="Lower runs first")

    idempotency_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    correlation_id = models.CharField(max_length=128, blank=True)

    available_at = models.DateTimeField(db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=100, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "jobs_job"
        indexes = [models.Index(fields=["state", "available_at", "priority"])]

    def __str__(self) -> str:
        return f"{self.job_type} [{self.state}] ({self.public_id})"


class WorkerHeartbeat(TimeStampedModel):
    """Proof that a worker process is alive and polling.

    The queue is a database table, so nothing raises when the worker dies - jobs
    simply accumulate in QUEUED and every uploaded report stays at RECEIVED
    forever. The user sees a report that never finishes processing and the
    system reports no error at all, because from the API's point of view
    everything succeeded.

    A worker writes here on every poll, idle or not. Absence of a recent
    heartbeat, especially alongside a non-empty queue, is what turns that silent
    stall into something monitoring can page on.
    """

    worker_id = models.CharField(max_length=64, unique=True)
    hostname = models.CharField(max_length=120, blank=True)
    job_types = models.CharField(
        max_length=255, blank=True, help_text="Restriction this worker runs with, if any"
    )
    last_beat_at = models.DateTimeField(default=timezone.now, db_index=True)
    jobs_processed = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "jobs_worker_heartbeat"
        indexes = [models.Index(fields=["last_beat_at"])]

    def __str__(self) -> str:
        return f"{self.worker_id}@{self.hostname}"

    @property
    def seconds_since_beat(self) -> float:
        return (timezone.now() - self.last_beat_at).total_seconds()
