"""The FastAPI intelligence service makes no authorization decisions, requires
the shared service token + correlation id, and never fabricates a score
(spec sections 32, 52, 57)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.main import app
from intelligence.settings import get_settings

client = TestClient(app)
TOKEN = get_settings().service_token


def test_healthz_is_open():
    assert client.get("/healthz").json()["status"] == "ok"


def test_infer_requires_service_token():
    resp = client.post("/v1/infer", json={
        "task": "cvd", "model_version": "1.0.0", "feature_schema_version": "fs-1",
        "features": {"glucose": 5.4}, "correlation_id": "c1",
    })
    assert resp.status_code == 401


def test_infer_requires_correlation_id():
    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": TOKEN},
        json={
            "task": "cvd", "model_version": "1.0.0", "feature_schema_version": "fs-1",
            "features": {"glucose": 5.4}, "correlation_id": "c1",
        },
    )
    assert resp.status_code == 400


def test_infer_without_artifact_returns_review_required_not_a_score():
    # A task/version with no registered artifact anywhere.
    resp = client.post(
        "/v1/infer",
        headers={"X-Service-Token": TOKEN, "X-Correlation-Id": "corr-abc"},
        json={
            "task": "unmodeled-task", "model_version": "0.0.0", "feature_schema_version": "fs-x",
            "features": {"glucose": 5.4}, "correlation_id": "corr-abc",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_score"] is None
    assert body["calibrated_score"] is None
    assert body["reliability"]["status"] == "REVIEW_REQUIRED"
    assert body["model"]["artifact_loaded"] is False
    assert resp.headers["X-Correlation-Id"] == "corr-abc"
