"""Training pipeline: artifact shape, metrics, determinism, no-leakage split
(spec sections 23, 30, 34)."""
from __future__ import annotations

import json

from intelligence.ml_service.train import FEATURE_ORDER, build_demo_model


def test_bundle_and_meta_are_written(tmp_path):
    bundle = build_demo_model("cvd", "1.0.0", tmp_path, seed=1)
    assert bundle.exists()
    meta = json.loads((tmp_path / "cvd-1.0.0.meta.json").read_text())
    assert meta["feature_order"] == FEATURE_ORDER
    assert set(meta["domain"]) == set(FEATURE_ORDER)
    assert "roc_auc" in meta["validation_metrics"]
    assert meta["validation_metrics"]["roc_auc"] > 0.7  # separable synthetic signal


def test_validation_metrics_include_subgroup_temporal_leakage_and_robustness(tmp_path):
    meta = json.loads(
        build_demo_model("cvd", "1.0.0", tmp_path, seed=1)
        .with_name("cvd-1.0.0.meta.json")
        .read_text()
    )
    m = meta["validation_metrics"]
    assert m["leakage_check"] == "passed"
    assert set(m["subgroup_roc_auc"]) == {"subgroup_0", "subgroup_1"}
    assert set(m["temporal_roc_auc"]) == {"period_0", "period_1", "period_2"}
    assert set(m["missing_data_robustness"]) == set(FEATURE_ORDER)
    # Each subgroup keeps some signal.
    assert all(v is None or v > 0.6 for v in m["subgroup_roc_auc"].values())


def test_training_is_deterministic_for_a_fixed_seed(tmp_path):
    m1 = build_demo_model("cvd", "1.0.0", tmp_path / "a", seed=5)
    m2 = build_demo_model("cvd", "1.0.0", tmp_path / "b", seed=5)
    meta1 = json.loads(m1.with_name("cvd-1.0.0.meta.json").read_text())
    meta2 = json.loads(m2.with_name("cvd-1.0.0.meta.json").read_text())
    assert meta1["validation_metrics"] == meta2["validation_metrics"]
    assert meta1["domain"] == meta2["domain"]


def test_calibration_improves_or_matches_brier_score(tmp_path):
    meta = json.loads(
        build_demo_model("cvd", "1.0.0", tmp_path, seed=3)
        .with_name("cvd-1.0.0.meta.json")
        .read_text()
    )
    m = meta["validation_metrics"]
    assert m["brier_calibrated"] <= m["brier_raw"] + 0.01


def test_registry_loads_the_bundle(tmp_path, monkeypatch):
    build_demo_model("cvd", "1.0.0", tmp_path, seed=2)
    monkeypatch.setenv("INTELLIGENCE_MODELS_DIR", str(tmp_path))
    from intelligence.ml_service import registry
    from intelligence.settings import get_settings

    get_settings.cache_clear()
    model = registry.load("cvd", "1.0.0")
    assert model is not None
    assert model.feature_schema_version == "fs-1.0.0"
    assert model.feature_order == FEATURE_ORDER
    assert registry.load("cvd", "0.0.1") is None
    get_settings.cache_clear()
