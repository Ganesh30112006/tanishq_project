"""The shared vocabulary every stage of document intelligence speaks.

These types exist so that "I could not read this" and "there was nothing
clinically relevant here" are different, named values that cannot be confused
for one another - the same distinction the cardiovascular engine already
draws. Every stage returns one of these; none of them raise to signal an
ordinary "no".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DocumentMediaType(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"
    TIFF = "image/tiff"
    UNKNOWN = "application/octet-stream"

    @property
    def is_image(self) -> bool:
        return self in (DocumentMediaType.PNG, DocumentMediaType.JPEG, DocumentMediaType.TIFF)


class TextSource(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    #: The PDF carried a usable embedded text layer; no OCR was needed.
    EMBEDDED_TEXT_LAYER = "EMBEDDED_TEXT_LAYER"
    #: The text came from an OCR engine and must be treated as such.
    OCR = "OCR"
    #: No text could be obtained by any means. The document goes to review.
    NONE = "NONE"


class OcrOutcome(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    OK = "OK"
    #: Text was produced but the engine's mean confidence is below the floor.
    #: The tokens are still returned; a later stage decides what to trust.
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    #: The engine ran and found no text at all.
    NO_TEXT_FOUND = "NO_TEXT_FOUND"
    #: No OCR engine is installed or reachable in this deployment.
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    #: The engine was present but errored on this input.
    FAILED = "FAILED"

    @property
    def produced_text(self) -> bool:
        return self in (OcrOutcome.OK, OcrOutcome.LOW_CONFIDENCE)


class ClassificationStatus(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    CLASSIFIED = "CLASSIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CompletenessOutcome(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID = "INVALID"
    CONFLICTING = "CONFLICTING"


class ReportType(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    """Report categories this module recognises.

    The values are kept aligned with ``apps.common.enums.ReportClass`` where
    they overlap so that a thin adapter can translate between the Django model
    and this library without a lookup table full of special cases. ``UNKNOWN``
    corresponds to ``ReportClass.OTHER``.
    """

    CBC = "CBC"
    LIPID_PROFILE = "LIPID"
    GLUCOSE = "GLUCOSE"
    HBA1C = "HBA1C"
    LIVER_FUNCTION = "LIVER"
    KIDNEY_FUNCTION = "KIDNEY"
    URINALYSIS = "URINALYSIS"
    RADIOLOGY = "RADIOLOGY"
    PATHOLOGY = "PATHOLOGY"
    PRESCRIPTION = "PRESCRIPTION"
    DISCHARGE_SUMMARY = "DISCHARGE"
    CLINICAL_NOTE = "CLINICAL_NOTE"
    UNKNOWN = "OTHER"


# --- file validation --------------------------------------------------
@dataclass(slots=True)
class FileValidation:
    media_type: DocumentMediaType
    declared_type: str
    size_bytes: int
    ok: bool
    problems: list[str] = field(default_factory=list)

    @property
    def is_pdf(self) -> bool:
        return self.media_type is DocumentMediaType.PDF


# --- text layer -----------------------------------------------------
@dataclass(slots=True)
class TextLayerResult:
    source: TextSource
    text: str
    pages: int
    chars: int
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.source is TextSource.EMBEDDED_TEXT_LAYER and self.chars > 0


# --- OCR ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Page-relative coordinates in the range 0..1, origin top-left."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class OcrToken:
    text: str
    page: int
    confidence: float
    bbox: BoundingBox | None = None


@dataclass(slots=True)
class OcrResult:
    outcome: OcrOutcome
    provider: str
    tokens: list[OcrToken] = field(default_factory=list)
    text: str = ""
    mean_confidence: float | None = None
    detail: str = ""

    @property
    def produced_text(self) -> bool:
        return self.outcome.produced_text and bool(self.text.strip())


# --- classification -------------------------------------------------
@dataclass(slots=True)
class ClassificationResult:
    report_type: ReportType | None
    confidence: float
    status: ClassificationStatus
    signals: dict[str, int] = field(default_factory=dict)
    detail: str = ""
