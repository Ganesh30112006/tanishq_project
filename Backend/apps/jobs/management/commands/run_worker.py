from __future__ import annotations

import logging
import signal
import time
import uuid

from django.core.management.base import BaseCommand
from django.db import DatabaseError

from apps.jobs.health import beat
from apps.jobs.runner import run_once

logger = logging.getLogger("caresense.jobs")


class Command(BaseCommand):
    help = "Run a background job worker loop (polls the database; no broker)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--types", nargs="*", default=None, help="Restrict to these job types")
        parser.add_argument("--idle-sleep", type=float, default=1.0)
        parser.add_argument("--once", action="store_true", help="Process a single job then exit")

    def handle(self, *args, **options) -> None:
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        stopping = {"flag": False}

        def _stop(*_a):
            stopping["flag"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        def _beat(processed: int) -> None:
            # A missed beat only makes the worker look stale for a moment;
            # letting it raise would stop the worker for good.
            try:
                beat(worker_id, job_types=options["types"], processed=processed)
            except DatabaseError:
                logger.warning("worker_beat_failed", extra={"worker_id": worker_id}, exc_info=True)

        self.stdout.write(f"Starting {worker_id}")
        processed = 0
        # Beat immediately, so a worker that starts and then wedges is still
        # distinguishable from one that was never started at all.
        _beat(processed)
        last_beat = time.monotonic()

        while not stopping["flag"]:
            # A job's own failure is handled inside run_once. A database error
            # while claiming one (a lock, a dropped connection) is passing, so
            # the pass is skipped and the next one tries again.
            try:
                job = run_once(worker_id=worker_id, job_types=options["types"])
            except DatabaseError:
                logger.warning("worker_poll_failed", extra={"worker_id": worker_id}, exc_info=True)
                job = None
            if job is not None:
                processed += 1

            # On every pass, but written at most once a second so a busy worker
            # does not spend its time updating its own heartbeat row.
            if time.monotonic() - last_beat >= 1.0:
                _beat(processed)
                last_beat = time.monotonic()

            if options["once"]:
                break
            if job is None:
                time.sleep(options["idle_sleep"])

        _beat(processed)
        self.stdout.write(f"Worker stopped after {processed} job(s)")
