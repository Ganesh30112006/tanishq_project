"""Job handler registry and single-step runner.

A deployment runs one or more worker processes that loop on :func:`run_once`.
Handlers are plain callables ``handler(payload: dict) -> dict``; they must be
idempotent and must re-load and re-authorize any resource they act on.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from apps.jobs.models import Job
from apps.jobs.services import JobService

logger = logging.getLogger("caresense.jobs")

Handler = Callable[[dict], dict]
_HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        if job_type in _HANDLERS:
            raise RuntimeError(f"Handler for '{job_type}' already registered.")
        _HANDLERS[job_type] = func
        return func

    return decorator


def get_handler(job_type: str) -> Handler | None:
    return _HANDLERS.get(job_type)


def run_once(*, worker_id: str, job_types: list[str] | None = None) -> Job | None:
    service = JobService()
    job = service.claim(worker_id=worker_id, job_types=job_types)
    if job is None:
        return None

    handler = get_handler(job.job_type)
    if handler is None:
        service.fail(job, f"No handler registered for job type '{job.job_type}'.")
        return job

    try:
        result = handler(job.payload) or {}
    except Exception as exc:  # noqa: BLE001 - the runner must not crash the worker
        logger.exception("job_failed", extra={"job_type": job.job_type, "job_id": str(job.public_id)})
        service.fail(job, f"{type(exc).__name__}: {exc}")
        return job

    service.succeed(job, result)
    return job
