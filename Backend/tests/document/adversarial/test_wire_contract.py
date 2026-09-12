"""The refusal has to survive the HTTP boundary.

Everything the adversarial suite establishes is worth nothing if the reason a
value was refused is lost between the intelligence service and Django. Django
is the side that opens a workflow, files a task or writes a clinical record,
and "we could not tell what this was" and "we read it and a person should
confirm what it means" send it in different directions.
"""
from __future__ import annotations

import base64
import io

from fastapi.testclient import TestClient

from intelligence.document.contracts import ValueStatus
from intelligence.main import app
from intelligence.settings import get_settings

client = TestClient(app)
TOKEN = get_settings().service_token


def _pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(400, 500))
    y = 440
    for line in lines:
        c.drawString(30, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buffer.getvalue()


def _post(lines: list[str]) -> dict:
    body = {
        "document_id": "doc_1",
        "content_base64": base64.b64encode(_pdf(lines)).decode("ascii"),
        "declared_media_type": "application/pdf",
        "correlation_id": "c1",
    }
    response = client.post(
        "/v1/documents/process", json=body,
        headers={"X-Service-Token": TOKEN, "X-Correlation-Id": "c1"},
    )
    assert response.status_code == 200, response.text
    return response.json()


CBC = [
    "COMPLETE BLOOD COUNT",
    "Hemoglobin 13.4 g/dL 13.0 - 17.0",
    "WBC 7.2 10^9/L 4.0 - 11.0",
    "Platelet Count 240 10^9/L 150 - 450",
]


def _value(body: dict, analyte: str) -> dict:
    return next(v for v in body["values"] if v["analyte"] == analyte)


def test_a_clean_value_crosses_the_boundary_marked_persistable():
    body = _post(CBC)
    hb = _value(body, "hemoglobin")
    assert hb["status"] == "OBSERVED"
    assert hb["persists_clinical_value"] is True
    assert hb["reason"] == ""


def test_a_refused_value_says_why_over_the_wire():
    body = _post([
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 1 3.4 g/dL 13.0 - 17.0",
        "WBC 7.2 10^9/L 4.0 - 11.0",
        "Platelet Count 240 10^9/L 150 - 450",
    ])
    hb = _value(body, "hemoglobin")
    assert hb["status"] == "AMBIGUOUS"
    assert hb["persists_clinical_value"] is False
    assert hb["reason"] == "more_than_one_number_on_the_line"
    assert hb["value"] is None


def test_a_conflict_crosses_the_boundary_as_a_conflict():
    body = _post([*CBC, "Hemoglobin 9.8 g/dL 13.0 - 17.0"])
    for value in body["values"]:
        if value["analyte"] == "hemoglobin":
            assert value["status"] == "CONFLICTING"
            assert value["persists_clinical_value"] is False
    assert any(i["code"] == "VALUES_CONFLICTING" for i in body["issues"])


def test_no_refused_value_is_ever_sent_as_persistable():
    """The single property Django is entitled to rely on."""
    body = _post([
        "COMPLETE BLOOD COUNT",
        "Hemoglobin 1 3.4 g/dL 13.0 - 17.0",
        "TSH <0.01 uIU/mL 0.4 - 4.0",
        "Ionized Calcium 4.6 mg/dL",
        "WBC 7.2 10^9/L 4.0 - 11.0",
        "Platelet Count 240 10^9/L 150 - 450",
    ])
    for value in body["values"]:
        persistable = value["persists_clinical_value"]
        assert persistable == (value["status"] == ValueStatus.OBSERVED.value)
        if not persistable:
            assert value["reason"], value


def test_every_status_the_service_can_emit_is_a_known_one():
    body = _post([*CBC, "Hemoglobin 9.8 g/dL 13.0 - 17.0", "TSH <0.01 uIU/mL"])
    known = {s.value for s in ValueStatus}
    for value in body["values"]:
        assert value["status"] in known


def test_the_schema_advertises_the_persistence_flag():
    """A caller reading the OpenAPI document must be able to find it."""
    schema = client.get("/openapi.json").json()
    props = schema["components"]["schemas"]["ValueOut"]["properties"]
    assert "persists_clinical_value" in props
    assert "reason" in props
