"""Out-of-distribution / reliability check (spec section 32).

Given a loaded model's validated domain, decide whether the input is inside
the model's scope. A blocking verdict (OUT_OF_DOMAIN / INSUFFICIENT_DATA /
REVIEW_REQUIRED) is never downgraded to VALID by callers.
"""
from __future__ import annotations

from intelligence.schemas import ReliabilityBlock, ReliabilityStatus


def reliability_for(model, features: dict[str, float]) -> ReliabilityBlock:
    missing = [name for name in model.feature_order if name not in features]
    if missing:
        return ReliabilityBlock(
            status=ReliabilityStatus.INSUFFICIENT_DATA, detail={"missing": missing}
        )

    out_of_domain = []
    for name, bounds in model.domain.items():
        if name not in features:
            continue
        value = features[name]
        lo, hi = bounds.get("min"), bounds.get("max")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            out_of_domain.append(name)

    if out_of_domain:
        return ReliabilityBlock(
            status=ReliabilityStatus.OUT_OF_DOMAIN, detail={"features": out_of_domain}
        )
    return ReliabilityBlock(status=ReliabilityStatus.VALID)
