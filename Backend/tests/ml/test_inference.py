"""Intelligence-service inference: calibration, OOD, SHAP, reproducibility,
model-version integrity (spec sections 30-35)."""
from __future__ import annotations

from tests.ml.conftest import IN_DOMAIN, infer


def test_in_domain_input_returns_calibrated_prediction_with_shap(ml_client):
    client, token = ml_client
    resp = infer(client, token, IN_DOMAIN)
    assert resp.status_code == 200
    body = resp.json()

    assert 0.0 <= body["raw_score"] <= 1.0
    assert 0.0 <= body["calibrated_score"] <= 1.0
    assert body["calibration_version"] == "cal-1.0.0"
    assert body["reliability"]["status"] == "VALID"
    assert body["model"]["artifact_loaded"] is True

    shap = body["shap"]
    assert {c["feature"] for c in shap} == set(IN_DOMAIN)
    # Ordered by absolute contribution.
    assert [abs(c["contribution"]) for c in shap] == sorted(
        (abs(c["contribution"]) for c in shap), reverse=True
    )


def test_inference_is_reproducible(ml_client):
    client, token = ml_client
    a = infer(client, token, IN_DOMAIN).json()
    b = infer(client, token, IN_DOMAIN).json()
    assert a["raw_score"] == b["raw_score"]
    assert a["calibrated_score"] == b["calibrated_score"]
    assert a["shap"] == b["shap"]


def test_out_of_domain_value_is_flagged_and_no_score_returned(ml_client):
    client, token = ml_client
    resp = infer(client, token, {**IN_DOMAIN, "glucose": 50.0})
    body = resp.json()
    assert body["reliability"]["status"] == "OUT_OF_DOMAIN"
    assert "glucose" in body["reliability"]["detail"]["features"]
    assert body["raw_score"] is None
    assert body["calibrated_score"] is None


def test_missing_feature_is_insufficient_data(ml_client):
    client, token = ml_client
    incomplete = {k: v for k, v in IN_DOMAIN.items() if k != "hdl"}
    body = infer(client, token, incomplete).json()
    assert body["reliability"]["status"] == "INSUFFICIENT_DATA"
    assert body["raw_score"] is None


def test_unknown_model_version_is_review_required(ml_client):
    client, token = ml_client
    body = infer(client, token, IN_DOMAIN, version="9.9.9").json()
    assert body["reliability"]["status"] == "REVIEW_REQUIRED"
    assert body["model"]["artifact_loaded"] is False


def test_feature_schema_mismatch_is_review_required(ml_client):
    client, token = ml_client
    body = infer(client, token, IN_DOMAIN, schema="fs-wrong").json()
    assert body["reliability"]["status"] == "REVIEW_REQUIRED"
    assert body["reliability"]["detail"]["expected"] == "fs-1.0.0"


def test_higher_risk_profile_scores_higher_than_lower_risk(ml_client):
    client, token = ml_client
    low = {"age": 35.0, "glucose": 4.8, "systolic_bp": 112.0, "bmi": 23.0, "hdl": 1.7}
    high = {"age": 70.0, "glucose": 8.0, "systolic_bp": 158.0, "bmi": 34.0, "hdl": 0.9}
    low_score = infer(client, token, low).json()["calibrated_score"]
    high_score = infer(client, token, high).json()["calibrated_score"]
    assert high_score > low_score
