"""Temporal-validity helpers (spec section 21).

An old result is never treated as current just because it exists. These
functions make "latest valid value" and "within the last N days" explicit
and testable.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, TypeVar

from django.utils import timezone


class HasObservedAt(Protocol):
    observed_at: dt.datetime


T = TypeVar("T", bound=HasObservedAt)


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    is_fresh: bool
    age: dt.timedelta
    max_age: dt.timedelta


def age_of(observed_at: dt.datetime, *, now: dt.datetime | None = None) -> dt.timedelta:
    now = now or timezone.now()
    return now - observed_at


def check_freshness(
    observed_at: dt.datetime, max_age_days: int, *, now: dt.datetime | None = None
) -> FreshnessResult:
    max_age = dt.timedelta(days=max_age_days)
    age = age_of(observed_at, now=now)
    return FreshnessResult(is_fresh=age <= max_age, age=age, max_age=max_age)


def latest(values: list[T]) -> T | None:
    """Most recently observed item, or ``None`` for an empty list."""
    if not values:
        return None
    return max(values, key=lambda v: v.observed_at)


def latest_fresh(
    values: list[T], max_age_days: int, *, now: dt.datetime | None = None
) -> T | None:
    """Most recent item that is still within ``max_age_days``."""
    now = now or timezone.now()
    candidates = [
        v for v in values if check_freshness(v.observed_at, max_age_days, now=now).is_fresh
    ]
    return latest(candidates)
