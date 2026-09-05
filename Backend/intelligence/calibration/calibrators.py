"""Probability calibration (spec section 31).

A raw model score is not presented as a clinically meaningful probability
until it has passed through a fitted calibrator (Platt / isotonic). The
calibrator and its version travel with the model artifact.
"""
from __future__ import annotations

from typing import Protocol


class Calibrator(Protocol):
    version: str

    def transform(self, raw_score: float) -> float: ...


class IdentityCalibrator:
    """Explicit no-op used only in tests / never in a clinical response."""

    version = "identity"

    def transform(self, raw_score: float) -> float:
        return raw_score
