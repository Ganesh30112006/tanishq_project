"""Parse a printed reference range into numbers, or admit it could not.

Lab reports write ranges a dozen ways: ``0 - 6``, ``0.0-6.0``, ``13.0 – 17.0``,
``< 200``, ``<=5``, ``> 40``, ``Up to 6``, ``Negative``. This turns the ones
that are numeric intervals into ``(low, high)`` and marks the rest as
qualitative or unparsed - it never invents a bound.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: A number, with optional thousands separators: "4,000 - 11,000 /uL" is
#: how a white-cell range is usually printed. The comma must be followed by
#: exactly three digits, so a decimal comma ("1,5") is left unparsed rather
#: than silently read as fifteen.
_NUMBER = r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?"
_DASH = r"[-‐-―−]"  # hyphen and the various unicode dashes

#: A unit printed alongside the range: "13.5 - 17.5 g/dL", "< 200 mg/dL",
#: "150 - 450 10^9/L". Very common on Indian reports, where the range column
#: repeats the unit. The same three shapes the result column accepts, so a
#: range is not held to a narrower idea of what a unit looks like than the
#: value beside it: a cell-count form, a per-volume form, or an ordinary unit.
#: A bare number can never match, so it cannot swallow the other end of an
#: interval.
_UNIT = (
    r"(?:x?10[\^*]?\d+/[A-Za-zµμ]+"
    r"|/[A-Za-zµμ]+"
    r"|[%A-Za-zµμ][A-Za-z0-9/^%*·.µμ\-]*)"
)

_INTERVAL = re.compile(
    rf"^\s*(?P<low>{_NUMBER})\s*(?P<low_unit>{_UNIT})?\s*{_DASH}\s*"
    rf"(?P<high>{_NUMBER})\s*(?P<unit>{_UNIT})?\s*$"
)
_UPPER = re.compile(
    rf"^\s*(?:<|<=|≤|up to|upto|less than)\s*(?P<high>{_NUMBER})\s*"
    rf"(?P<unit>{_UNIT})?\s*$",
    re.I,
)
_LOWER = re.compile(
    rf"^\s*(?:>|>=|≥|over|greater than)\s*(?P<low>{_NUMBER})\s*"
    rf"(?P<unit>{_UNIT})?\s*$",
    re.I,
)
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
    #: The unit the *range* was printed in, when it printed one. Kept as the
    #: laboratory wrote it and never converted: the printed unit is what says
    #: which quantity the lab meant, exactly as the label does for BUN against
    #: urea. Empty when the range column carried no unit of its own, which by
    #: the layout convention means the same unit as the result beside it.
    unit: str = ""

    @property
    def is_numeric(self) -> bool:
        return self.kind in ("interval", "upper_bound", "lower_bound")


def _number(token: str) -> float:
    return float(token.replace(",", ""))


def parse_reference_range(text: str) -> ReferenceRange:
    raw = (text or "").strip().strip("()[]").strip()
    if not raw:
        return ReferenceRange(text="", kind="absent")

    cleaned = raw.replace("–", "-").replace("—", "-")

    match = _INTERVAL.match(cleaned)
    if match:
        low, high = _number(match["low"]), _number(match["high"])
        if low > high:
            low, high = high, low
        low_unit = (match["low_unit"] or "").strip()
        unit = (match["unit"] or "").strip()
        if low_unit and unit and low_unit.lower() != unit.lower():
            # "13.5 g/dL - 17.5 g/L" is not a range anyone should compare
            # against. Admitted as unparsed rather than resolved by picking one.
            return ReferenceRange(text=raw, kind="unparsed")
        return ReferenceRange(
            text=raw, low=low, high=high, kind="interval", unit=unit or low_unit
        )

    match = _UPPER.match(cleaned)
    if match:
        return ReferenceRange(
            text=raw, high=_number(match["high"]), kind="upper_bound",
            unit=(match["unit"] or "").strip(),
        )

    match = _LOWER.match(cleaned)
    if match:
        return ReferenceRange(
            text=raw, low=_number(match["low"]), kind="lower_bound",
            unit=(match["unit"] or "").strip(),
        )

    if raw.lower() in _QUALITATIVE:
        return ReferenceRange(text=raw, kind="qualitative")

    return ReferenceRange(text=raw, kind="unparsed")
