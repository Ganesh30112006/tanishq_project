from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def demo_artifacts(tmp_path_factory):
    """Train the demo model once for the test session."""
    from intelligence.ml_service.train import build_demo_model

    out = tmp_path_factory.mktemp("artifacts")
    build_demo_model("cvd", "1.0.0", out, seed=0)
    return out


@pytest.fixture
def ml_client(demo_artifacts, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_MODELS_DIR", str(demo_artifacts))
    from intelligence.settings import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from intelligence.main import app

    client = TestClient(app)
    token = get_settings().service_token
    yield client, token
    get_settings.cache_clear()


IN_DOMAIN = {"age": 60.0, "glucose": 6.0, "systolic_bp": 135.0, "bmi": 29.0, "hdl": 1.1}


def infer(client, token, features, *, version="1.0.0", schema="fs-1.0.0", corr="c-1"):
    return client.post(
        "/v1/infer",
        headers={"X-Service-Token": token, "X-Correlation-Id": corr},
        json={
            "task": "cvd",
            "model_version": version,
            "feature_schema_version": schema,
            "features": features,
            "correlation_id": corr,
        },
    )
