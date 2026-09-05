"""Data-quality evaluation (spec sections 17, 48).

``evaluate_values`` runs a few deterministic checks and returns a structured
report. It is a data-quality metric, not a medical score. Statistical outlier
helpers only compute flags; they never mutate or drop data (spec section 18).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from apps.common.services import BaseService


@dataclass(slots=True)
class QualityReport:
    completeness: float
    required_missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    out_of_range: list[str] = field(default_factory=list)
    passed: bool = True

    def grade(self) -> str:
        if self.completeness >= 0.99 and not self.invalid and not self.out_of_range:
            return "HIGH"
        if self.completeness >= 0.8 and not self.invalid:
            return "MEDIUM"
        return "LOW"


class DataQualityEngine(BaseService):
    def evaluate_values(
        self, *, required: list[str], values: dict[str, object], ranges: dict[str, dict] | None = None
    ) -> QualityReport:
        ranges = ranges or {}
        missing = [name for name in required if values.get(name) in (None, "")]
        invalid: list[str] = []
        out_of_range: list[str] = []

        for name, raw in values.items():
            if raw in (None, ""):
                continue
            try:
                num = float(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                invalid.append(name)
                continue
            bounds = ranges.get(name) or {}
            lo, hi = bounds.get("min"), bounds.get("max")
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                out_of_range.append(name)

        present = len(required) - len(missing)
        completeness = round(present / len(required), 4) if required else 1.0
        return QualityReport(
            completeness=completeness,
            required_missing=missing,
            invalid=invalid,
            out_of_range=out_of_range,
            passed=not missing and not invalid,
        )


def iqr_bounds(values: list[float], k: float = 1.5) -> tuple[float, float]:
    """Return (lower, upper) fences. Values outside are candidates for review,
    not deletion."""
    if len(values) < 4:
        return (float("-inf"), float("inf"))
    ordered = sorted(values)
    q1 = statistics.quantiles(ordered, n=4)[0]
    q3 = statistics.quantiles(ordered, n=4)[2]
    iqr = q3 - q1
    return (q1 - k * iqr, q3 + k * iqr)


def mad_score(value: float, values: list[float]) -> float:
    """Modified z-score based on median absolute deviation."""
    if not values:
        return 0.0
    med = statistics.median(values)
    deviations = [abs(v - med) for v in values]
    mad = statistics.median(deviations) or 1e-9
    return 0.6745 * (value - med) / mad
