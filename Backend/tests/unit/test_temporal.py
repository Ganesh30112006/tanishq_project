from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from apps.common.temporal import check_freshness, latest, latest_fresh

NOW = timezone.now()


@dataclass
class Obs:
    observed_at: dt.datetime
    label: str


def test_check_freshness_boundary():
    assert check_freshness(NOW - dt.timedelta(days=30), 30, now=NOW).is_fresh
    assert not check_freshness(NOW - dt.timedelta(days=31), 30, now=NOW).is_fresh


def test_latest_picks_most_recent():
    items = [Obs(NOW - dt.timedelta(days=5), "old"), Obs(NOW - dt.timedelta(days=1), "new")]
    assert latest(items).label == "new"


def test_latest_fresh_ignores_stale_even_if_more_recent_than_nothing():
    items = [Obs(NOW - dt.timedelta(days=400), "stale")]
    assert latest_fresh(items, 90, now=NOW) is None
