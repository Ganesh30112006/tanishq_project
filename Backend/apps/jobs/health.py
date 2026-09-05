"""Is the background pipeline actually working?

A database-backed queue fails silently. When the worker stops, the API keeps
accepting uploads and returning 201, jobs pile up in QUEUED, and every report
sits at RECEIVED indefinitely. Nothing errors, so nothing alerts, and the first
report of the outage is a person saying their file never processed.

This module turns that silence into a signal that a load balancer or a
monitoring probe can read.
"""
from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.common.enums import JobState
from apps.jobs.models import Job, WorkerHeartbeat

#: A worker beats on every poll, so a gap much longer than its idle sleep means
#: it is wedged, not merely quiet.
STALE_AFTER_SECONDS = 90

#: How long a job may sit unclaimed before the backlog is itself the problem,
#: even if some worker is technically alive.
BACKLOG_AGE_SECONDS = 300


def queue_status(*, now: dt.datetime | None = None) -> dict:
    """A structured verdict on the job pipeline.

    ``status`` is one of ``ok``, ``degraded`` or ``down``:

    * **down** - work is queued and no worker has beaten recently. Reports are
      not being processed at all.
    * **degraded** - a worker is alive but the queue is not draining, or jobs
      have exhausted their retries and need a person.
    * **ok** - a live worker, and nothing stuck.
    """
    now = now or timezone.now()
    stale_before = now - dt.timedelta(seconds=STALE_AFTER_SECONDS)
    backlog_before = now - dt.timedelta(seconds=BACKLOG_AGE_SECONDS)

    live = list(WorkerHeartbeat.objects.filter(last_beat_at__gte=stale_before))
    all_workers = WorkerHeartbeat.objects.count()

    queued = Job.objects.filter(state=JobState.QUEUED).count()
    running = Job.objects.filter(state=JobState.RUNNING).count()
    failed = Job.objects.filter(state=JobState.FAILED).count()
    stale_queued = Job.objects.filter(
        state=JobState.QUEUED, available_at__lt=backlog_before
    ).count()

    oldest = (
        Job.objects.filter(state=JobState.QUEUED)
        .order_by("available_at")
        .values_list("available_at", flat=True)
        .first()
    )
    oldest_age = round((now - oldest).total_seconds(), 1) if oldest else 0.0

    problems: list[str] = []
    if not live and queued:
        problems.append(
            f"No worker has reported in {STALE_AFTER_SECONDS}s and {queued} job(s) "
            f"are waiting. Uploaded reports are not being processed. "
            f"Start one with: manage.py run_worker"
        )
    elif not live and all_workers == 0:
        problems.append(
            "No worker has ever reported. Background processing has not been "
            "started in this environment."
        )
    elif not live:
        problems.append(f"No worker has reported in {STALE_AFTER_SECONDS}s.")

    if live and stale_queued:
        problems.append(
            f"{stale_queued} job(s) have been queued for over "
            f"{BACKLOG_AGE_SECONDS}s despite a live worker."
        )
    if failed:
        problems.append(f"{failed} job(s) have exhausted their retries and need review.")

    if not live and queued:
        status = "down"
    elif problems:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "workers_alive": len(live),
        "workers_known": all_workers,
        "queued": queued,
        "running": running,
        "failed": failed,
        "stale_queued": stale_queued,
        "oldest_queued_age_seconds": oldest_age,
        "problems": problems,
    }


def beat(worker_id: str, *, job_types=None, processed: int = 0) -> WorkerHeartbeat:
    """Record that ``worker_id`` is alive and polling."""
    import socket

    row, _ = WorkerHeartbeat.objects.update_or_create(
        worker_id=worker_id,
        defaults={
            "hostname": socket.gethostname()[:120],
            "job_types": ",".join(job_types or [])[:255],
            "last_beat_at": timezone.now(),
            "jobs_processed": processed,
        },
    )
    return row
