"""Feature processing (spec sections 12, 30).

Turns the validated feature dict Django sends into the exact ordered vector a
model artifact expects. Preprocessing is deterministic and versioned; it must
match the ``preprocessing_version`` recorded on the model. No imputation of
clinical values happens here - missing required features are reported back,
not filled in.

``polars`` is part of the ``intelligence`` extra and is imported lazily so the
base install stays lean.
"""
from __future__ import annotations


def to_frame(features: dict[str, float]):
    import polars as pl

    return pl.DataFrame([features]) if features else pl.DataFrame()


def order_vector(
    features: dict[str, float], feature_order: list[str]
) -> tuple[list[float], list[str]]:
    missing = [name for name in feature_order if name not in features]
    vector = [float(features[name]) for name in feature_order if name in features]
    return vector, missing
