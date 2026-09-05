from __future__ import annotations

import signal
import time
import uuid

from django.core.management.base import BaseCommand

from apps.jobs.health import beat
from apps.jobs.runner import run_once


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

        self.stdout.write(f"Starting {worker_id}")
        processed = 0
        # Beat immediately, so a worker that starts and then wedges is still
        # distinguishable from one that was never started at all.
        beat(worker_id, job_types=options["types"], processed=processed)
        last_beat = time.monotonic()

        while not stopping["flag"]:
            job = run_once(worker_id=worker_id, job_types=options["types"])
            if job is not None:
                processed += 1

            # On every pass, but written at most once a second so a busy worker
            # does not spend its time updating its own heartbeat row.
            if time.monotonic() - last_beat >= 1.0:
                beat(worker_id, job_types=options["types"], processed=processed)
                last_beat = time.monotonic()

            if options["once"]:
                break
            if job is None:
                time.sleep(options["idle_sleep"])

        beat(worker_id, job_types=options["types"], processed=processed)
        self.stdout.write(f"Worker stopped after {processed} job(s)")
