"""The OCR adapter contract.

A provider is anything with a name, a way to say whether it can run in this
deployment, and a ``run`` that turns image bytes into an
:class:`~intelligence.document.contracts.OcrResult`. Implementations live
beside this file (``local.py``) or are registered by a deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from intelligence.document.contracts import DocumentMediaType, OcrResult

#: Below this mean token confidence (0..1) a result is tagged LOW_CONFIDENCE.
#: The tokens are still returned; the extraction stage decides what to do with
#: a low-confidence read. It is not OCR's job to silently drop them.
DEFAULT_CONFIDENCE_FLOOR = 0.55


@dataclass(slots=True)
class OcrRequest:
    image_bytes: bytes
    media_type: DocumentMediaType
    languages: tuple[str, ...] = ("eng",)
    #: Providers that support it may deskew / threshold before recognition.
    preprocess: bool = True
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class OCRProvider(Protocol):
    #: Stable identifier used to select this provider by name.
    name: str

    def is_available(self) -> bool:
        """Whether this provider can run here right now.

        Must not raise. A provider whose engine is missing returns ``False``;
        callers then fall back or return ``ENGINE_UNAVAILABLE``.
        """
        ...

    def run(self, request: OcrRequest) -> OcrResult:
        """Recognise text. Never raises for an ordinary failure - it returns
        an :class:`OcrResult` whose ``outcome`` says what went wrong."""
        ...
