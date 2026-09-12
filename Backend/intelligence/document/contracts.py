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


class ReferenceStatus(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    WITHIN = "WITHIN_REFERENCE_RANGE"
    ABOVE = "ABOVE_REFERENCE_RANGE"
    BELOW = "BELOW_REFERENCE_RANGE"
    #: No range on the report, a qualitative range, or one that could not be
    #: parsed. The value is not compared against a guess.
    UNKNOWN = "UNKNOWN"


class UnitRelation(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    """How the unit a result is printed in relates to the unit of its range.

    A result and a reference range can only be compared when their units are
    the same quantity. Reading "5.4 mg/dL" against "< 200 mmol/L" produces a
    confident, wrong answer, and the report gives every clue needed to avoid
    it - so the relationship is established explicitly and named, rather than
    assumed by comparing the numbers.
    """

    #: Both sides carry the same printed unit, or the range printed none of
    #: its own - which by the column convention means the result's unit.
    SAME_UNIT = "SAME_UNIT"
    #: Different units, and this analyte has a verified conversion between
    #: them. The comparison is made in the canonical unit; neither the printed
    #: result nor the printed range is rewritten.
    CONVERTIBLE = "CONVERTIBLE"
    #: Both units are recognised and there is no conversion between them for
    #: this analyte. The range cannot be applied to this result.
    INCOMPATIBLE = "INCOMPATIBLE"
    #: At least one of the two units is not one this system knows, so whether
    #: they agree cannot be established either way.
    UNKNOWN = "UNKNOWN"

    @property
    def comparable(self) -> bool:
        return self in (UnitRelation.SAME_UNIT, UnitRelation.CONVERTIBLE)


class ValueStatus(str, Enum):  # noqa: UP042 - str mixin kept for JSON/DRF-style serialisation
    """Why a value is, or is not, a clinical fact this system will stand behind.

    Distinguishing these is what makes the no-fabrication guarantee
    *observable*. If every failure were one kind of "needs review", a report
    where the parser could not tell what was measured would look exactly like
    one where it read the value perfectly and the printed flag disagreed - and
    those need completely different things from a person.

    The vocabulary is kept aligned with ``apps.common.enums.ClinicalDataState``
    where the two overlap, so a value crossing the HTTP boundary into Django
    does not have to be translated through a table of special cases.

    Exactly one of these means "a clinical value may be persisted from this":
    ``OBSERVED``. Everything else is a reason not to, and says which reason.
    """

    #: Passed every deterministic check; safe to treat as an observed value.
    OBSERVED = "OBSERVED"
    #: The parser could not confidently establish *what was measured* - the
    #: analyte, the value or the unit. An unrecognised test name, a missing or
    #: unreadable unit, a result given as a bound ("< 0.01") rather than a
    #: number, two numbers where one was expected. No clinical value is
    #: persisted, and the reason is not that the value looks odd; it is that
    #: there is no value to look at.
    AMBIGUOUS = "AMBIGUOUS"
    #: The same analyte was reported more than once on this document with
    #: different values. Both are carried and neither is chosen.
    CONFLICTING = "CONFLICTING"
    #: Outside the plausibility bounds for the analyte: a read error, not a
    #: sick patient. Never persisted as a clinical value.
    INVALID = "INVALID"
    #: The source text for this value could not be read with enough confidence
    #: to vouch for the characters in it.
    UNREADABLE = "UNREADABLE"
    #: Analyte, value and unit were all established and are plausible, but
    #: something about the *interpretation* is unresolved - a printed H/L flag
    #: that disagrees with the computed reference status, a reference range
    #: that could not be parsed. Unlike AMBIGUOUS, there is a fact here; a
    #: person is being asked to confirm what it means.
    NEEDS_REVIEW = "NEEDS_REVIEW"
    #: Only ever the answer to "what does this document say about analyte X?".
    #: Never the status of an extracted value - a value that was not found was
    #: not extracted. See ``DocumentResult.outcome_for``.
    NOT_FOUND = "NOT_FOUND"

    @property
    def persists_clinical_value(self) -> bool:
        """The whole no-fabrication guarantee, in one place."""
        return self is ValueStatus.OBSERVED


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
    THYROID = "THYROID"
    ELECTROLYTES = "ELECTROLYTES"
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
