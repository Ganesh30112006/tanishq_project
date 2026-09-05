from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.main import app
from intelligence.settings import get_settings

client = TestClient(app)
TOKEN = get_settings().service_token
H = {"X-Service-Token": TOKEN, "X-Correlation-Id": "c-nlp"}


def _extract(text):
    return client.post("/v1/extract", headers=H, json={"text": text, "correlation_id": "c-nlp"})


def test_extracts_analyte_value_unit_with_confidence():
    body = _extract("Glucose: 5.4 mmol/L\nHbA1c: 48 mmol/mol\n").json()
    analytes = {e["analyte"]: e for e in body["entities"]}
    assert set(analytes) == {"glucose", "hba1c"}
    assert analytes["glucose"]["value"] == 5.4
    assert analytes["glucose"]["unit"] == "mmol/L"
    assert analytes["glucose"]["entity_confidence"] >= 0.9


def test_negated_mention_is_not_a_measurement():
    body = _extract("no evidence of glucose intolerance").json()
    if body["entities"]:
        assert body["entities"][0]["negated"] is True
        assert body["entities"][0]["value"] is None


def test_uncertain_mention_is_flagged():
    body = _extract("Glucose: 7.2 mmol/L borderline").json()
    assert body["entities"][0]["uncertain"] is True


def test_ocr_normalizes_text_and_reports_confidence():
    r = client.post(
        "/v1/ocr", headers=H,
        json={"text": "Glu-\ncose:   5.4   mmol/L", "correlation_id": "c-nlp"},
    )
    body = r.json()
    assert body["status"] == "OK"
    assert "Glucose:" in body["text"]
    assert 0.0 <= body["blocks"][0]["ocr_confidence"] <= 1.0
