"""Contract test: Django's IntelligenceClient against the real FastAPI service.

Routes the client's HTTP calls into an in-process ``TestClient`` for
``intelligence.main.app`` so the two sides are checked against each other -
request shape out, response parsing back - without a network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.common.intelligence import IntelligenceClient
from intelligence.main import app
from intelligence.settings import get_settings

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="session")
def demo_artifacts(tmp_path_factory):
    from intelligence.ml_service.train import build_demo_model

    out = tmp_path_factory.mktemp("contract_artifacts")
    build_demo_model("cvd", "1.0.0", out, seed=0)
    return out


@pytest.fixture
def wired_client(demo_artifacts, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_MODELS_DIR", str(demo_artifacts))
    get_settings.cache_clear()
    fastapi_client = TestClient(app)

    def fake_post(url, *, json, headers, timeout):
        path = url.split("/v1", 1)[1]
        return fastapi_client.post(f"/v1{path}", json=json, headers=headers)

    monkeypatch.setattr("httpx.post", fake_post)
    client = IntelligenceClient(
        base_url="http://intelligence.test", token=get_settings().service_token, timeout=5
    )
    yield client
    get_settings.cache_clear()


def test_infer_round_trips(wired_client):
    result = wired_client.infer(
        task="cvd", model_version="1.0.0", feature_schema_version="fs-1.0.0",
        features={"age": 60.0, "glucose": 6.0, "systolic_bp": 135.0, "bmi": 29.0, "hdl": 1.1},
        correlation_id="corr-contract",
    )
    assert result.reliability_status == "VALID"
    assert 0.0 <= result.calibrated_score <= 1.0
    assert {c["feature"] for c in result.shap} == {"age", "glucose", "systolic_bp", "bmi", "hdl"}


def test_infer_missing_feature_round_trips_as_insufficient(wired_client):
    result = wired_client.infer(
        task="cvd", model_version="1.0.0", feature_schema_version="fs-1.0.0",
        features={"age": 60.0}, correlation_id="corr-contract",
    )
    assert result.reliability_status == "INSUFFICIENT_DATA"
    assert result.raw_score is None


def test_ai_answer_round_trips(wired_client):
    result = wired_client.ai_answer(
        kind="QA", question="What is the glucose?",
        context_blocks=[{
            "ref": "labresult:1", "type": "lab_result", "label": "glucose",
            "content": "5.4 mmol/L", "state": "OBSERVED",
        }],
        knowledge=[], correlation_id="corr-contract",
    )
    assert result.status == "OK"
    assert "labresult:1" in result.context_refs_used
    assert result.flags["invented_facts"] is False
