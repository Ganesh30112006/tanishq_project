"""What an annotator records about the *reading* of a report.

This is the first of the two benchmarks and it answers one question:

    text or image  ->  structured evidence.   Did we read it correctly?

It is kept entirely separate from the clinical reasoning benchmark, and that
separation is the point. A detector can have flawless reasoning and be fed a
misread haemoglobin; extraction can be perfect and feed a detector that draws
an unsafe conclusion. Scored together, the two failures are indistinguishable,
and the one number they produce tells nobody which layer to fix.

The annotator here does not need to be a clinician. They need to be able to
read a laboratory report accurately and transcribe what it says: the test
name, the number, the unit, the printed range, the printed flag, the section
it sat under. That is a different skill from deciding whether a result is
clinically meaningful, and asking for it separately makes the corpus much
cheaper to produce.

The field that does the most work is ``should_not_be_extracted``. A report is
mostly *not* results - page numbers, accession numbers, ages, dates, method
notes - and a parser that turns any of those into a clinical value has
fabricated one. Recording the lines that must yield nothing is how that gets
measured rather than assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

#: Bump when the fields change. A corpus records which version it used, and
#: sets annotated under different versions are not pooled.
EXTRACTION_SCHEMA_VERSION = "benchmark-extraction-1"

#: Two values count as the same number within this relative tolerance. Set
#: tight: this is transcription, not measurement, and 13.4 against 13.5 is a
#: misread rather than a rounding difference.
VALUE_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class FieldAnnotation:
    """One result line, transcribed exactly as the report prints it."""

    #: The canonical analyte name this line reports, or "" when the annotator
    #: judges it is not one of the analytes this system models.
    analyte: str
    #: The test name exactly as printed, which is what the parser sees.
    printed_label: str
    value: float | None = None
    unit: str = ""
    reference_text: str = ""
    printed_flag: str = ""
    section: str = ""
    #: True when this line must yield no clinical value at all - report
    #: furniture, a censored result, a line the annotator could not read.
    should_not_be_extracted: bool = False
    why_not: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.printed_label.strip():
            raise ValueError("a field annotation records the label as printed")
        if self.should_not_be_extracted:
            if not self.why_not.strip():
                raise ValueError(
                    f"{self.printed_label!r}: a line marked as yielding nothing "
                    f"must say why, because that reason is what the parser is "
                    f"being asked to reproduce"
                )
            if self.value is not None:
                raise ValueError(
                    f"{self.printed_label!r}: marked as yielding nothing but "
                    f"carries a value"
                )
        elif self.analyte and self.value is None:
            raise ValueError(
                f"{self.printed_label!r}: names an analyte but no value, and is "
                f"not marked as yielding nothing. Which is it?"
            )

    @property
    def key(self) -> str:
        """What a system value is matched against."""
        return self.analyte or f"<unmodelled:{self.printed_label.strip().lower()}>"

    def comparable(self) -> dict[str, str]:
        """The attributes scored one by one, as comparable tokens."""
        return {
            "value": "" if self.value is None else f"{self.value:.6g}",
            "unit": self.unit.strip().lower(),
            "reference_text": " ".join(self.reference_text.split()).lower(),
            "printed_flag": self.printed_flag.strip().upper(),
            "section": " ".join(self.section.split()).upper(),
        }


@dataclass(frozen=True, slots=True)
class DocumentAnnotation:
    """Everything one annotator recorded about reading one document."""

    document_id: str
    annotator_id: str
    annotated_on: date
    #: The report type this document is, in the vocabulary of
    #: ``intelligence.document.contracts.ReportType``.
    document_type: str
    fields: tuple[FieldAnnotation, ...]
    #: False when the document cannot be read at all - too dark, too skewed,
    #: a photograph of the wrong page. The parser is expected to say so too.
    readable: bool = True
    schema_version: str = EXTRACTION_SCHEMA_VERSION
    note: str = ""

    def __post_init__(self) -> None:
        if not self.document_id or not self.annotator_id:
            raise ValueError("a document id and an annotator id are required")
        if self.schema_version != EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                f"{self.document_id}: annotated under {self.schema_version}, "
                f"this code speaks {EXTRACTION_SCHEMA_VERSION}"
            )
        keys = [f.key for f in self.fields]
        if len(set(keys)) != len(keys):
            raise ValueError(
                f"{self.document_id}: the same line is annotated twice. If the "
                f"report really prints one analyte twice, that is a conflict "
                f"and belongs in the note."
            )
        if not self.readable and self.fields:
            raise ValueError(
                f"{self.document_id}: marked unreadable but carries fields"
            )

    def field(self, key: str) -> FieldAnnotation | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def extractable(self) -> tuple[FieldAnnotation, ...]:
        """The lines that must yield a value."""
        return tuple(f for f in self.fields if not f.should_not_be_extracted)

    @property
    def refusable(self) -> tuple[FieldAnnotation, ...]:
        """The lines that must yield nothing."""
        return tuple(f for f in self.fields if f.should_not_be_extracted)


@dataclass(frozen=True, slots=True)
class ExtractionAdjudication:
    """A third annotator's ruling where the first two transcribed differently."""

    adjudicator_id: str
    adjudicated_on: date
    document_type: str = ""
    fields: tuple[FieldAnnotation, ...] = ()
    disagreement_reason: str = ""

    def __post_init__(self) -> None:
        if not self.adjudicator_id:
            raise ValueError("an adjudication needs a named adjudicator")
        if not self.fields and not self.document_type:
            raise ValueError("an adjudication that rules on nothing is not one")
        if not self.disagreement_reason.strip():
            raise ValueError(
                "an adjudication must record why the annotators differed - two "
                "people reading the same printed number differently is the "
                "most useful signal this corpus produces"
            )

    def field(self, key: str) -> FieldAnnotation | None:
        return next((f for f in self.fields if f.key == key), None)


@dataclass(frozen=True, slots=True)
class ExtractionItem:
    """One document, everything recorded about reading it, and any ruling."""

    document_id: str
    source_sha256: str
    annotations: tuple[DocumentAnnotation, ...]
    adjudication: ExtractionAdjudication | None = None
    #: How the document reached the system: a clean PDF, a scan, a photograph.
    capture: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.annotations:
            raise ValueError(f"{self.document_id}: no annotations")
        annotators = [a.annotator_id for a in self.annotations]
        if len(set(annotators)) != len(annotators):
            raise ValueError(
                f"{self.document_id}: the same annotator appears twice"
            )
        for annotation in self.annotations:
            if annotation.document_id != self.document_id:
                raise ValueError(
                    f"{self.document_id}: carries an annotation for "
                    f"{annotation.document_id}"
                )

    @property
    def annotator_count(self) -> int:
        return len(self.annotations)

    @property
    def keys(self) -> set[str]:
        """Every line any annotator recorded, extractable or not."""
        return {f.key for a in self.annotations for f in a.fields}


@dataclass(slots=True)
class ExtractionCorpus:
    corpus_id: str
    items: list[ExtractionItem] = field(default_factory=list)
    description: str = ""
    schema_version: str = EXTRACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        seen = [item.document_id for item in self.items]
        if len(set(seen)) != len(seen):
            raise ValueError(f"{self.corpus_id}: a document id appears twice")

    def __len__(self) -> int:
        return len(self.items)
