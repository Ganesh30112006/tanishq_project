"""POST /v1/documents/process - the boundary Django calls.

The endpoint resolves nothing on its own: it takes the bytes Django hands it,
runs the deterministic pipeline, and returns a structured result. It requires
the service token and a correlation id like every other intelligence endpoint,
and it never accepts a filesystem path or a patient id.
"""
from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient

from intelligence.main import app
from intelligence.settings import get_settings

client = TestClient(app)
TOKEN = get_settings().service_token


def _pdf(lines: list[str] | None) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(400, 500))
    y = 440
    for line in lines or []:
        c.drawString(30, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buffer.getvalue()


CBC = [
    "COMPLETE BLOOD COUNT",
    "Hemoglobin 13.4 g/dL 13.0 - 17.0",
    "WBC 7.2 10^9/L 4.0 - 11.0",
    "Platelet Count 240 10^9/L 150 - 450",
]


def _post(body: dict, *, token: str = TOKEN, corr: str = "c1"):
    headers = {"X-Correlation-Id": corr}
    if token is not None:
        headers["X-Service-Token"] = token
    return client.post("/v1/documents/process", json=body, headers=headers)


def _body(data: bytes, **over):
    return {
        "document_id": "doc_1",
        "content_base64": base64.b64encode(data).decode("ascii"),
        "declared_media_type": "application/pdf",
        "correlation_id": "c1",
        **over,
    }


# --- the boundary is guarded the same as every other endpoint --------
def test_the_service_token_is_required():
    assert _post(_body(_pdf(CBC)), token=None).status_code == 401


def test_a_correlation_id_is_required():
    assert _post(_body(_pdf(CBC)), corr="").status_code == 400


def test_the_schema_has_no_path_or_patient_field():
    """A field that took a path or a patient id would let the service fetch."""
    schema = client.get("/openapi.json").json()
    props = schema["components"]["schemas"]["DocumentProcessRequest"]["properties"]
    assert "content_base64" in props
    for forbidden in ("path", "file_path", "content_reference", "patient_id",
                      "storage_key", "url"):
        assert forbidden not in props


# --- a clean report is extracted ------------------------------------
def test_a_clean_cbc_pdf_comes_back_extracted_with_provenance():
    resp = _post(_body(_pdf(CBC)))
    assert resp.status_code == 200
    body = resp.json()

    assert body["document_id"] == "doc_1"
    assert body["disposition"] == "EXTRACTED"
    assert body["report_type"] == "CBC"
    assert body["completeness"]["outcome"] == "COMPLETE"
    analytes = {v["analyte"] for v in body["values"]}
    assert analytes == {"hemoglobin", "wbc", "platelets"}

    hb = next(v for v in body["values"] if v["analyte"] == "hemoglobin")
    assert hb["normalized"]["value"] == 134.0
    assert hb["reference_status"] == "WITHIN_REFERENCE_RANGE"
    prov = hb["provenance"]
    assert prov["source_sha256"] == body["source_sha256"]
    assert prov["section"] == "COMPLETE BLOOD COUNT"
    assert prov["text_source"] == "EMBEDDED_TEXT_LAYER"


def test_the_response_echoes_the_document_id_for_correlation():
    body = _post(_body(_pdf(CBC), document_id="abc-999")).json()
    assert body["document_id"] == "abc-999"


# --- unreadable / rejected paths ----------------------------------
def test_a_non_report_file_is_rejected():
    body = _post(_body(b"MZ\x90\x00 not a pdf")).json()
    assert body["disposition"] == "REJECTED_FILE"
    assert any(i["severity"] == "HIGH" for i in body["issues"])
    assert body["values"] == []


def test_an_image_with_no_ocr_engine_reports_unreadable_and_capabilities():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    body = _post(_body(png, declared_media_type="image/png")).json()

    # In an environment without Tesseract this is UNREADABLE; the capability
    # block says why, so the caller is not left guessing.
    if not body["capabilities"]["ocr"]["available"]:
        assert body["disposition"] == "UNREADABLE"
        assert any(i["code"] == "OCR_UNAVAILABLE" for i in body["issues"])
    assert "ocr" in body["capabilities"]


def test_malformed_base64_is_a_422_not_a_500():
    resp = _post({"document_id": "d", "content_base64": "!!!not base64!!!",
                  "correlation_id": "c1"})
    assert resp.status_code == 422


def test_an_unknown_operation_is_rejected():
    resp = _post(_body(_pdf(CBC), requested_operations=["extract_text", "hallucinate"]))
    assert resp.status_code == 422


# --- requested_operations truncates the response -----------------
def test_stopping_at_classify_returns_no_values():
    body = _post(_body(_pdf(CBC),
                       requested_operations=["extract_text", "classify"])).json()
    assert body["classification"] is not None
    assert body["values"] == []
    assert body["completeness"] is None


def test_stopping_at_extract_values_keeps_values_but_not_completeness():
    body = _post(_body(_pdf(CBC),
                       requested_operations=["extract_text", "classify",
                                             "extract_values"])).json()
    assert len(body["values"]) == 3
    assert body["completeness"] is None


# --- the capability probe ---------------------------------------
def test_the_capability_probe_lists_stage_availability():
    resp = client.get("/v1/documents/capabilities",
                      headers={"X-Service-Token": TOKEN, "X-Correlation-Id": "c1"})
    assert resp.status_code == 200
    caps = resp.json()["capabilities"]
    assert caps["pdf_text_layer"]["available"] is True
    assert caps["classification"]["available"] is True
    assert caps["llm"]["available"] is False   # fails closed until built
    assert caps["rag"]["available"] is False


@pytest.mark.parametrize("path", ["/v1/documents/capabilities"])
def test_capability_probe_needs_the_token(path):
    assert client.get(path).status_code in (401, 503)


# --- findings come back over the same call ------------------------
ANEMIA_CBC = [
    "COMPLETE BLOOD COUNT",
    "Hemoglobin 9.8 g/dL 13.0 - 17.0 L",
    "MCV 72 fL 80 - 100 L",
    "WBC 7.2 10^9/L 4.0 - 11.0",
    "Platelet Count 240 10^9/L 150 - 450",
]


def test_findings_are_returned_with_their_level_and_validation_status():
    body = _post(_body(_pdf(ANEMIA_CBC), patient_sex="male")).json()
    block = body["findings"]

    codes = {f["code"]: f for f in block["findings"]}
    assert "ANEMIA_PATTERN" in codes
    assert "MICROCYTOSIS_PATTERN" in codes
    assert codes["ANEMIA_PATTERN"]["level"] == 2
    assert block["needs_human_review"] is True
    assert block["range_table_version"] and block["knowledge_version"]

    for finding in block["findings"]:
        assert finding["validation_status"] == "NOT_VALIDATED"
        assert finding["human_review_required"] is True
        assert finding["explanation"].strip()
        assert ":" in finding["detector"]


def test_a_level_3_finding_names_the_evidence_it_lacked():
    body = _post(_body(_pdf(ANEMIA_CBC), patient_sex="male")).json()
    iron = next(
        f for f in body["findings"]["findings"]
        if f["code"] == "POSSIBLE_IRON_DEFICIENCY_ANEMIA"
    )
    assert iron["level"] == 3
    assert iron["confidence"] == "PROVISIONAL"
    assert iron["evidence_missing"] == ["ferritin"]
    assert {e["key"] for e in iron["evidence_used"]} >= {
        "ANEMIA_PATTERN", "MICROCYTOSIS_PATTERN"
    }


def test_evidence_is_traceable_back_to_the_page_and_line():
    body = _post(_body(_pdf(ANEMIA_CBC), patient_sex="male")).json()
    anemia = next(
        f for f in body["findings"]["findings"] if f["code"] == "ANEMIA_PATTERN"
    )
    used = anemia["evidence_used"][0]
    assert used["key"] == "hemoglobin"
    assert used["reference_source"] == "report"
    assert used["page"] == 1
    assert used["source_text"].strip()


def test_findings_can_be_skipped_by_not_requesting_them():
    body = _post(_body(
        _pdf(ANEMIA_CBC),
        requested_operations=["extract_text", "classify", "extract_values", "validate"],
    )).json()
    assert body["findings"] is None


def test_an_unknown_patient_sex_value_is_refused():
    resp = _post(_body(_pdf(ANEMIA_CBC), patient_sex="unspecified"))
    assert resp.status_code == 422


def test_the_capability_probe_reports_finding_detection():
    body = _post(_body(_pdf(ANEMIA_CBC))).json()
    assert body["capabilities"]["finding_detection"]["available"] is True
    assert "NOT_VALIDATED" in body["capabilities"]["finding_detection"]["detail"]
