"""The Django side of the document boundary.

``IntelligenceClient.process_document`` sends authorized *content* over HTTP and
never a pointer the service could dereference. These tests stub the transport
and assert the request shape, plus that the response maps onto a
``DocumentProcessResult`` Django can act on.
"""
from __future__ import annotations

import base64
import json

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.common.errors import UpstreamUnavailable
from apps.common.intelligence import DocumentProcessResult, IntelligenceClient

pytestmark = pytest.mark.django_db

_SAMPLE_RESPONSE = {
    "document_id": "doc_42",
    "disposition": "EXTRACTED",
    "source_sha256": "abcd",
    "media_type": "application/pdf",
    "text_source": "EMBEDDED_TEXT_LAYER",
    "ocr_outcome": None,
    "classification": {"type": "CBC", "confidence": 0.9, "status": "CLASSIFIED",
                       "signals": {"CBC": 12}, "detail": ""},
    "report_type": "CBC",
    "values": [{"analyte": "hemoglobin", "printed_label": "Hemoglobin",
                "value": 13.4, "unit": "g/dL", "status": "OBSERVED", "issues": []}],
    "completeness": {"outcome": "COMPLETE", "schema_version": 1,
                     "missing_required": [], "invalid": [], "conflicting": [],
                     "ambiguous": [], "unrecognised_labels": []},
    "issues": [],
    "capabilities": {"ocr": {"available": False, "detail": "no engine"}},
    "notes": [],
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else _SAMPLE_RESPONSE

    def json(self):
        return self._payload


@pytest.fixture
def captured(monkeypatch):
    calls: dict[str, object] = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls["url"] = url
        calls["json"] = json
        calls["headers"] = headers
        return _FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    return calls


def _client():
    return IntelligenceClient(base_url="http://intel.test", token="t0ken", timeout=5)  # noqa: S106


def test_the_request_sends_content_not_a_path_or_patient_id(captured):
    _client().process_document(
        document_id="doc_42",
        content=b"%PDF-1.5 fake",
        declared_media_type="application/pdf",
        correlation_id="corr-1",
    )

    assert captured["url"] == "http://intel.test/v1/documents/process"
    body = captured["json"]
    assert body["document_id"] == "doc_42"
    assert base64.b64decode(body["content_base64"]) == b"%PDF-1.5 fake"
    # The scoped-payload rule: nothing the service could resolve itself.
    serialised = json.dumps(body)
    for forbidden in ("patient_id", "file_path", "storage", "content_reference",
                      "media/reports", "/var/", "s3://"):
        assert forbidden not in serialised
    assert captured["headers"]["X-Service-Token"] == "t0ken"
    assert captured["headers"]["X-Correlation-Id"] == "corr-1"


def test_the_response_maps_onto_a_result_django_can_act_on(captured):
    result = _client().process_document(
        document_id="doc_42", content=b"x",
        declared_media_type="application/pdf", correlation_id="c",
    )
    assert isinstance(result, DocumentProcessResult)
    assert result.disposition == "EXTRACTED"
    assert result.report_type == "CBC"
    assert result.values[0]["analyte"] == "hemoglobin"
    assert result.needs_human_review is False


def test_a_needs_review_disposition_flips_the_helper(monkeypatch):
    payload = {**_SAMPLE_RESPONSE, "disposition": "NEEDS_REVIEW"}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse(payload=payload))
    result = _client().process_document(
        document_id="d", content=b"x", declared_media_type="application/pdf",
        correlation_id="c",
    )
    assert result.needs_human_review is True


def test_a_high_severity_issue_flips_the_helper_even_if_extracted(monkeypatch):
    payload = {**_SAMPLE_RESPONSE, "disposition": "EXTRACTED",
               "issues": [{"code": "VALUES_REJECTED", "severity": "HIGH", "detail": ""}]}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse(payload=payload))
    result = _client().process_document(
        document_id="d", content=b"x", declared_media_type="application/pdf",
        correlation_id="c",
    )
    assert result.needs_human_review is True


def test_operations_are_forwarded_only_when_given(captured):
    _client().process_document(
        document_id="d", content=b"x", declared_media_type="application/pdf",
        correlation_id="c", operations=["extract_text", "classify"],
    )
    assert captured["json"]["requested_operations"] == ["extract_text", "classify"]


def test_a_5xx_becomes_upstream_unavailable(monkeypatch):
    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse(status_code=503))
    with pytest.raises(UpstreamUnavailable):
        _client().process_document(
            document_id="d", content=b"x", declared_media_type="application/pdf",
            correlation_id="c",
        )


def test_the_client_refuses_to_run_without_a_service_token(settings):
    settings.INTELLIGENCE = {**settings.INTELLIGENCE, "SERVICE_TOKEN": ""}
    with pytest.raises(ImproperlyConfigured):
        IntelligenceClient()
