"""A passing database error must not stop the worker.

The worker is the only thing that reads uploaded reports. When it exits, every
upload after that sits at "Being read" until someone notices and restarts it.
"""
# Regression: ISSUE-008 — "database is locked" in the heartbeat killed the worker
# Found by /qa on 2026-10-22
# Report: .gstack/qa-reports/run-20261022T144739Z/qa-report-127-0-0-1-2026-10-22.md
from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import OperationalError

from apps.jobs.management.commands import run_worker

pytestmark = pytest.mark.django_db


def _locked(*_args, **_kwargs):
    raise OperationalError("database is locked")


def test_a_locked_database_while_claiming_a_job_does_not_stop_the_worker(monkeypatch):
    monkeypatch.setattr(run_worker, "run_once", _locked)
    call_command("run_worker", "--once", "--idle-sleep", "0")


def test_a_locked_database_while_beating_does_not_stop_the_worker(monkeypatch):
    monkeypatch.setattr(run_worker, "beat", _locked)
    call_command("run_worker", "--once", "--idle-sleep", "0")
