"""FastAPI AI endpoint: boundary security + extractive, non-fabricating output
(spec sections 36-38, 52)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.main import app
from intelligence.settings import get_settings

client = TestClient(app)
TOKEN = get_settings().service_token
HEADERS = {"X-Service-Token": TOKEN, "X-Correlation-Id": "c-ai"}


def _body(question, context_blocks=None, knowledge=None):
    return {
        "kind": "QA",
        "question": question,
        "context_blocks": context_blocks or [],
        "knowledge": knowledge or [],
        "correlation_id": "c-ai",
    }


def test_requires_service_token():
    r = client.post("/v1/ai/answer", json=_body("anything"))
    assert r.status_code == 401


def test_requires_correlation_id():
    r = client.post("/v1/ai/answer", headers={"X-Service-Token": TOKEN}, json=_body("x"))
    assert r.status_code == 400


def test_empty_context_yields_insufficient_context_not_a_guess():
    r = client.post("/v1/ai/answer", headers=HEADERS, json=_body("What is the patient's glucose?"))
    body = r.json()
    assert body["status"] == "INSUFFICIENT_CONTEXT"
    assert "does not contain" in body["answer"]
    assert body["flags"]["missing_information"] is True
    assert body["flags"]["invented_facts"] is False


def test_observed_value_is_restated_and_labelled():
    blocks = [
        {"ref": "labresult:1", "type": "lab_result", "label": "glucose",
         "content": "5.4 mmol/L", "state": "OBSERVED", "observed_at": "2024-05-01"}
    ]
    body = client.post(
        "/v1/ai/answer", headers=HEADERS, json=_body("What is the glucose?", blocks)
    ).json()
    assert body["status"] == "OK"
    assert body["sections"]["observed_data"] == ["glucose: 5.4 mmol/L (observed 2024-05-01)"]
    assert "5.4 mmol/L" in body["sections"]["ai_summary"]
    assert "does not provide clinical interpretation" in body["sections"]["interpretation"]
    assert "labresult:1" in body["context_refs_used"]
    assert "OBSERVED DATA:" in body["answer"] and "AI SUMMARY:" in body["answer"]


def test_non_observed_value_goes_to_uncertainty_not_observed():
    blocks = [
        {"ref": "rt:1", "type": "report_test", "label": "glucose",
         "content": "5.4", "state": "AMBIGUOUS"}
    ]
    body = client.post("/v1/ai/answer", headers=HEADERS, json=_body("glucose?", blocks)).json()
    assert body["sections"]["observed_data"] == []
    assert any("AMBIGUOUS" in u for u in body["sections"]["uncertainty"])
    assert body["flags"]["contains_uncertainty"] is True


def test_question_about_absent_topic_is_reported_as_missing():
    blocks = [
        {"ref": "labresult:1", "type": "lab_result", "label": "glucose",
         "content": "5.4 mmol/L", "state": "OBSERVED"}
    ]
    body = client.post(
        "/v1/ai/answer", headers=HEADERS, json=_body("What is the HbA1c?", blocks)
    ).json()
    assert any("hba1c" in m.lower() for m in body["sections"]["missing_information"])
