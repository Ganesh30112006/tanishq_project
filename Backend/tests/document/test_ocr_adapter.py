"""The OCR adapter: swappable engine, and a missing engine is a clean result.

Most CI machines have no Tesseract binary, so the important paths here are the
ones that run when OCR is *not* available. Those must return a named
``ENGINE_UNAVAILABLE`` outcome with no tokens - never an empty string that a
caller might mistake for "the page was blank", and never an exception.
"""
from __future__ import annotations

import pytest

from intelligence.document.contracts import DocumentMediaType, OcrOutcome
from intelligence.document.ocr import (
    LocalTesseractProvider,
    available_providers,
    default_provider,
    get_provider,
    register_provider,
)
from intelligence.document.ocr.provider import OCRProvider, OcrRequest

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _request() -> OcrRequest:
    return OcrRequest(image_bytes=_PNG, media_type=DocumentMediaType.PNG)


# --- the local provider degrades safely -----------------------------
def test_local_provider_conforms_to_the_protocol():
    assert isinstance(LocalTesseractProvider(), OCRProvider)


def test_local_provider_without_the_engine_returns_engine_unavailable():
    provider = LocalTesseractProvider()
    if provider.is_available():
        pytest.skip("Tesseract is installed in this environment")

    result = provider.run(_request())
    assert result.outcome is OcrOutcome.ENGINE_UNAVAILABLE
    assert result.tokens == []
    assert result.text == ""
    assert not result.produced_text
    assert "not installed" in result.detail


def test_is_available_never_raises():
    # Whatever the environment, this returns a bool rather than throwing.
    assert isinstance(LocalTesseractProvider().is_available(), bool)


# --- the registry lets a deployment choose ------------------------
def test_a_deployment_can_register_and_select_an_alternative_provider():
    class FakeCloudOCR:
        name = "fake-cloud"

        def is_available(self) -> bool:
            return True

        def run(self, request: OcrRequest):
            from intelligence.document.contracts import OcrResult, OcrToken

            token = OcrToken(text="Hemoglobin", page=1, confidence=0.99)
            return OcrResult(
                outcome=OcrOutcome.OK, provider=self.name, tokens=[token],
                text="Hemoglobin", mean_confidence=0.99,
            )

    register_provider("fake-cloud", FakeCloudOCR)
    try:
        assert "fake-cloud" in available_providers()
        provider = get_provider("fake-cloud")
        assert provider.name == "fake-cloud"
        result = provider.run(_request())
        assert result.outcome is OcrOutcome.OK
        assert result.produced_text
    finally:
        from intelligence.document.ocr import registry

        registry._FACTORIES.pop("fake-cloud", None)


def test_selecting_an_unknown_provider_is_a_loud_error():
    with pytest.raises(KeyError):
        get_provider("no-such-engine")


def test_default_provider_is_returned_even_when_nothing_is_available(monkeypatch):
    """A caller should never have to guard against ``None`` from here."""
    monkeypatch.delenv("DOCUMENT_OCR_PROVIDER", raising=False)
    provider = default_provider()
    assert provider is not None
    assert hasattr(provider, "run")


def test_env_var_selects_the_provider(monkeypatch):
    monkeypatch.setenv("DOCUMENT_OCR_PROVIDER", "tesseract-local")
    assert default_provider().name == "tesseract-local"


# --- token shape, when an engine is present ----------------------
def test_token_output_carries_text_page_bbox_and_confidence():
    provider = LocalTesseractProvider()
    if not provider.is_available():
        pytest.skip("Tesseract not installed; token shape covered by the fake above")

    result = provider.run(_request())
    for token in result.tokens:
        assert isinstance(token.text, str) and token.text
        assert token.page >= 1
        assert 0.0 <= token.confidence <= 1.0
        if token.bbox is not None:
            assert 0.0 <= token.bbox.x0 <= token.bbox.x1 <= 1.0000001
