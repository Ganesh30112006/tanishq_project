"""Select an OCR provider by name, or take the deployment default.

A deployment picks its engine with the ``DOCUMENT_OCR_PROVIDER`` environment
variable. If that is unset, the default is the first registered provider that
reports itself available; if none is available, the local Tesseract provider is
returned anyway so that callers get a clean ``ENGINE_UNAVAILABLE`` result
rather than a ``None`` to guard against.
"""
from __future__ import annotations

import os
from collections.abc import Callable

from intelligence.document.ocr.local import LocalTesseractProvider
from intelligence.document.ocr.provider import OCRProvider

_FACTORIES: dict[str, Callable[[], OCRProvider]] = {
    LocalTesseractProvider.name: LocalTesseractProvider,
}


def register_provider(name: str, factory: Callable[[], OCRProvider]) -> None:
    """Add or replace a provider. Intended for deployment wiring and tests."""
    _FACTORIES[name] = factory


def available_providers() -> list[str]:
    return sorted(
        name for name, factory in _FACTORIES.items() if _safe_available(factory())
    )


def get_provider(name: str) -> OCRProvider:
    if name not in _FACTORIES:
        raise KeyError(
            f"unknown OCR provider {name!r}; registered: {sorted(_FACTORIES)}"
        )
    return _FACTORIES[name]()


def default_provider() -> OCRProvider:
    configured = os.environ.get("DOCUMENT_OCR_PROVIDER", "").strip()
    if configured:
        return get_provider(configured)
    for name in sorted(_FACTORIES):
        provider = _FACTORIES[name]()
        if _safe_available(provider):
            return provider
    return LocalTesseractProvider()


def _safe_available(provider: OCRProvider) -> bool:
    try:
        return bool(provider.is_available())
    except Exception:  # noqa: BLE001 - availability probing must never raise
        return False
