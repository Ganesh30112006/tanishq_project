"""Parse a printed reference range into numbers, or admit it could not.

Lab reports write ranges a dozen ways: ``0 - 6``, ``0.0-6.0``, ``13.0 – 17.0``,
``< 200``, ``<=5``, ``> 40``, ``Up to 6``, ``Negative``. This turns the ones
that are numeric intervals into ``(low, high)`` and marks the rest as
qualitative or unparsed - it never invents a bound.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_DASH = r"[-‐-―−]"  # hyphen and the various unicode dashes

_INTERVAL = re.compile(
    rf"^\s*(?P<low>{_NUMBER})\s*{_DASH}\s*(?P<high>{_NUMBER})\s*$"
)
_UPPER = re.compile(rf"^\s*(?:<|<=|≤|up to|upto|less than)\s*(?P<high>{_NUMBER})\s*$", re.I)
_LOWER = re.compile(rf"^\s*(?:>|>=|≥|over|greater than)\s*(?P<low>{_NUMBER})\s*$", re.I)
_QUALITATIVE = {
    "negative", "positive", "nil", "absent", "not detected", "non-reactive",
    "reactive", "trace", "normal", "see comment", "see note",
}


@dataclass(frozen=True, slots=True)
class ReferenceRange:
    text: str
    low: float | None = None
    high: float | None = None
    #: "interval" | "upper_bound" | "lower_bound" | "qualitative" | "unparsed" | "absent"
    kind: str = "absent"

    @property
    def is_numeric(self) -> bool:
        return self.kind in ("interval", "upper_bound", "lower_bound")


def parse_reference_range(text: str) -> ReferenceRange:
    raw = (text or "").strip().strip("()[]").strip()
    if not raw:
        return ReferenceRange(text="", kind="absent")

    cleaned = raw.replace("–", "-").replace("—", "-")

    match = _INTERVAL.match(cleaned)
    if match:
        low, high = float(match["low"]), float(match["high"])
        if low > high:
            low, high = high, low
        return ReferenceRange(text=raw, low=low, high=high, kind="interval")

    match = _UPPER.match(cleaned)
    if match:
        return ReferenceRange(text=raw, high=float(match["high"]), kind="upper_bound")

    match = _LOWER.match(cleaned)
    if match:
        return ReferenceRange(text=raw, low=float(match["low"]), kind="lower_bound")

    if raw.lower() in _QUALITATIVE:
        return ReferenceRange(text=raw, kind="qualitative")

    return ReferenceRange(text=raw, kind="unparsed")
