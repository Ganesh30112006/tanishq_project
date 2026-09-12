"""Proportions, reported so that small numbers cannot pretend to be large ones.

Both benchmarks compute precision and recall, and both would otherwise report
four out of four as 1.000 - a statement four observations do not support, and
the most likely way for a detector to be trusted on nothing.
"""
from __future__ import annotations

import math

#: Wilson score interval coverage. Named rather than assumed, so a report can
#: say which interval it used.
CONFIDENCE_LEVEL = 0.95
_Z = 1.959963984540054


def wilson_interval(successes: int, trials: int) -> tuple[float, float] | None:
    """A confidence interval for a proportion that behaves at the extremes.

    The normal approximation gives (1.0, 1.0) for four out of four. Wilson does
    not, which is the entire reason it is used here.
    """
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + _Z**2 / trials
    centre = (p + _Z**2 / (2 * trials)) / denominator
    spread = (
        _Z * math.sqrt(p * (1 - p) / trials + _Z**2 / (4 * trials**2))
    ) / denominator
    return (round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4))


def ratio(numerator: int, denominator: int) -> float | None:
    """A proportion, or ``None`` when there is nothing to divide by.

    Zero and "not estimable" are different answers, and returning 0.0 for the
    second is how a benchmark reports a perfect score for a detector nobody
    tested.
    """
    return numerator / denominator if denominator else None


def f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)
