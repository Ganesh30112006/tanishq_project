from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone

from apps.audit.context import get_request_id
from apps.common.enums import JobState
from apps.common.services import BaseService
from apps.jobs.models import Job


class JobService(BaseService):
    def enqueue(
        self,
        job_type: str,
        payload: dict,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        max_attempts: int = 3,
        priority: int = 0,
        delay_seconds: int = 0,
    ) -> Job:
        if idempotency_key:
            existing = Job.objects.filter(idempotency_key=idempotency_key).first()
            if existing is not None:
                return existing
        return Job.objects.create(
            job_type=job_type,
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id or get_request_id() or "",
            max_attempts=max_attempts,
            priority=priority,
            available_at=timezone.now() + dt.timedelta(seconds=delay_seconds),
        )

    @transaction.atomic
    def claim(self, *, worker_id: str, job_types: list[str] | None = None) -> Job | None:
        qs = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(state__in=[JobState.QUEUED, JobState.RETRYING], available_at__lte=timezone.now())
            .order_by("priority", "available_at")
        )
        if job_types:
            qs = qs.filter(job_type__in=job_types)
        job = qs.first()
        if job is None:
            return None
        job.state = JobState.RUNNING
        job.attempts += 1
        job.started_at = timezone.now()
        job.locked_by = worker_id[:100]
        job.locked_at = timezone.now()
        job.save(update_fields=["state", "attempts", "started_at", "locked_by", "locked_at", "updated_at"])
        return job

    @transaction.atomic
    def succeed(self, job: Job, result: dict | None = None) -> Job:
        job.state = JobState.SUCCEEDED
        job.result = result or {}
        job.error = ""
        job.finished_at = timezone.now()
        job.locked_by = ""
        job.save(update_fields=["state", "result", "error", "finished_at", "locked_by", "updated_at"])
        return job

    @transaction.atomic
    def fail(self, job: Job, error: str, *, retry_backoff_seconds: int = 60) -> Job:
        job.error = error[:5000]
        job.locked_by = ""
        if job.attempts < job.max_attempts:
            job.state = JobState.RETRYING
            job.available_at = timezone.now() + dt.timedelta(seconds=retry_backoff_seconds)
        else:
            job.state = JobState.FAILED
            job.finished_at = timezone.now()
        job.save(update_fields=["state", "error", "available_at", "finished_at", "locked_by", "updated_at"])
        return job

    @transaction.atomic
    def cancel(self, job: Job) -> Job:
        if job.state in (JobState.SUCCEEDED, JobState.FAILED):
            return job
        job.state = JobState.CANCELLED
        job.finished_at = timezone.now()
        job.locked_by = ""
        job.save(update_fields=["state", "finished_at", "locked_by", "updated_at"])
        return job
