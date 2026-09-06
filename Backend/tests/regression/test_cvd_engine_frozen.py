"""Same inputs -> same cardiovascular result.

Document-intelligence work is about to begin in a sibling part of the tree.
This file is the tripwire: if any of that work, or a dependency it pulls in,
changes what the CVD engine says for a fixed input, one of these assertions
fails with a diff against a number that was written down by hand.

The expectations live in ``frozen_baseline`` as literal constants, produced by
scoring the shipped artifact once and recording the answers. They are not
recomputed here from the model, because a test that recomputes proves only
that the code agrees with itself.
"""
from __future__ import annotations

import pytest

from intelligence.ml_service.registry import load
from tests.regression import frozen_baseline as FB

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module")
def model():
    loaded = load("cvd", FB.MODEL_VERSION)
    if loaded is None:
        pytest.skip(f"cvd-{FB.MODEL_VERSION}.joblib not built in this checkout")
    return loaded


# --- the artifact's identity is pinned ---------------------------------
def test_the_frozen_version_strings_still_describe_the_artifact(model):
    assert model.version == FB.MODEL_VERSION
    assert model.feature_schema_version == FB.FEATURE_SCHEMA_VERSION
    assert model.preprocessing_version == FB.PREPROCESSING_VERSION
    assert model.calibration_version == FB.CALIBRATION_VERSION
    assert model.explanation_version == FB.EXPLANATION_VERSION


def test_the_feature_order_is_unchanged(model):
    """The estimator consumes a positional array; a reorder is silent and fatal."""
    assert list(model.feature_order) == FB.FEATURE_ORDER


def test_the_validated_domain_is_unchanged(model):
    """This is the boundary the system refuses to extrapolate past."""
    assert {k: dict(v) for k, v in model.domain.items()} == FB.VALIDATED_DOMAIN


def test_no_calibrator_appeared_where_none_was_selected(model):
    """3.1.0 selected calibration "none". A calibrator here would mean the
    calibrated score has silently diverged from the raw one."""
    assert model.calibrator is None


# --- the scores are bit-stable within tolerance ----------------------
def _score_raw(model, features: dict) -> float:
    row = [[features[name] for name in model.feature_order]]
    return float(model.estimator.predict_proba(row)[0][1])


@pytest.mark.parametrize("vector", FB.GOLDEN_VECTORS, ids=lambda v: v["label"])
def test_raw_estimator_output_matches_the_frozen_value(model, vector):
    got = _score_raw(model, vector["features"])
    assert abs(got - vector["raw_score"]) <= FB.SCORE_TOLERANCE, (
        f"{vector['label']}: estimator now returns {got!r}, "
        f"frozen baseline is {vector['raw_score']!r}. If this change is "
        f"intended it needs a new model version, not an edited constant."
    )


# --- and through the whole serving path ------------------------------
@pytest.fixture(scope="module")
def infer_client():
    from fastapi.testclient import TestClient

    from intelligence.main import app
    from intelligence.settings import get_settings

    return TestClient(app), get_settings().service_token


@pytest.mark.parametrize("vector", FB.GOLDEN_VECTORS, ids=lambda v: v["label"])
def test_inference_endpoint_returns_the_frozen_score_and_verdict(infer_client, model, vector):
    client, token = infer_client
    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": token, "X-Correlation-Id": "frozen-regression"},
        json={
            "task": "cvd",
            "model_version": FB.MODEL_VERSION,
            "feature_schema_version": FB.FEATURE_SCHEMA_VERSION,
            "features": vector["features"],
            "correlation_id": "frozen-regression",
        },
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["reliability"]["status"] == vector["reliability"], (
        f"{vector['label']}: reliability verdict moved from "
        f"{vector['reliability']} to {body['reliability']['status']}"
    )
    assert abs(body["raw_score"] - vector["raw_score"]) <= FB.SCORE_TOLERANCE
    assert abs(body["calibrated_score"] - vector["calibrated_score"]) <= FB.SCORE_TOLERANCE
    assert body["model"]["artifact_loaded"] is True


# --- ordering the baseline was built to demonstrate ------------------
def test_risk_still_rises_monotonically_with_the_obvious_risk_factors(model):
    """A cheap sanity check with a clinical direction: at a fixed age and sex,
    a higher pressure and being a smoker must not lower the estimate."""
    base = {"age": 60.0, "is_male": 1.0, "systolic_bp": 120.0, "current_smoker": 0.0}
    higher_bp = {**base, "systolic_bp": 170.0}
    smoker = {**base, "current_smoker": 1.0}

    assert _score_raw(model, higher_bp) > _score_raw(model, base)
    assert _score_raw(model, smoker) > _score_raw(model, base)
