"""Model artifact registry (spec sections 33, 34).

A model artifact is a single joblib bundle keyed by ``<task>-<version>.joblib``
under ``models_dir``. It carries the estimator, the fitted calibrator, the
exact feature order, the validated input domain, and every version string
needed for reproducibility. Loading validates that the bundle's task/version
match what was requested; a mismatch or a missing file yields ``None`` and the
inference endpoint responds ``REVIEW_REQUIRED`` rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from intelligence.settings import get_settings

BUNDLE_KEYS = {
    "task",
    "model_version",
    "feature_schema_version",
    "preprocessing_version",
    "calibration_version",
    "explanation_version",
    "feature_order",
    "domain",
    "estimator",
}


@dataclass(frozen=True, slots=True)
class LoadedModel:
    task: str
    version: str
    feature_schema_version: str
    preprocessing_version: str
    calibration_version: str
    explanation_version: str
    feature_order: list[str]
    domain: dict[str, dict[str, float]]
    estimator: Any
    calibrator: Any | None
    #: "isotonic" (maps probability->probability) or "platt" (logistic on
    #: the logit). They are applied differently; see router._calibrate.
    calibrator_kind: str
    validation_metrics: dict[str, Any]


def artifact_path(task: str, version: str) -> Path:
    return Path(get_settings().models_dir) / f"{task}-{version}.joblib"


@lru_cache(maxsize=32)
def _load_bundle(path_str: str, mtime: float) -> dict:
    import joblib

    return joblib.load(path_str)


def load(task: str, version: str) -> LoadedModel | None:
    path = artifact_path(task, version)
    if not path.exists():
        return None
    bundle = _load_bundle(str(path), path.stat().st_mtime)
    missing = BUNDLE_KEYS - set(bundle)
    if missing:
        raise ValueError(f"Model bundle {path.name} is missing keys: {sorted(missing)}")
    if bundle["task"] != task or bundle["model_version"] != version:
        return None
    return LoadedModel(
        task=bundle["task"],
        version=bundle["model_version"],
        feature_schema_version=bundle["feature_schema_version"],
        preprocessing_version=bundle["preprocessing_version"],
        calibration_version=bundle["calibration_version"],
        explanation_version=bundle["explanation_version"],
        feature_order=list(bundle["feature_order"]),
        domain=dict(bundle["domain"]),
        estimator=bundle["estimator"],
        calibrator=bundle.get("calibrator"),
        calibrator_kind=bundle.get("calibrator_kind", "isotonic"),
        validation_metrics=dict(bundle.get("validation_metrics", {})),
    )
