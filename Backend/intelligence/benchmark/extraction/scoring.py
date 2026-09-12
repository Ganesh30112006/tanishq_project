"""Did we read the report correctly?

Four things are counted, and the headline is not precision.

**Detection.** Which result lines the parser found: precision, recall, F1 over
analytes, with Wilson intervals.

**Transcription.** Of the lines it found, how many of the value, unit,
reference range, printed flag and section it got right. Scored per attribute,
because a parser that reads every number correctly and every unit wrongly is a
different problem from one that does the reverse, and a single accuracy figure
hides both.

**Fabrication.** The headline. A value the parser produced that the annotators
say is not there, or a value it produced that differs from what the report
prints. This is the number that matters: a missed result is a gap a person can
see, and a wrong result is one nobody can. They are never added together.

**Refusal.** Lines the annotators marked as yielding nothing - page numbers,
accession numbers, censored results - and whether the parser also yielded
nothing. A parser is not measured only on what it reads; most of a report is
not a result.

A value the parser produced but marked as not persistable is **not** a
fabrication. Refusing out loud is the behaviour the whole status ladder exists
to produce, and counting it as an error would push the system towards
confident guesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from intelligence.benchmark.adjudication import LabelSource, resolve
from intelligence.benchmark.extraction.schema import (
    VALUE_TOLERANCE,
    ExtractionCorpus,
    ExtractionItem,
    FieldAnnotation,
)
from intelligence.benchmark.statistics import CONFIDENCE_LEVEL, f1, ratio, wilson_interval

#: The attributes transcription is scored on, one by one.
ATTRIBUTES = ("value", "unit", "reference_text", "printed_flag", "section")


@dataclass(frozen=True, slots=True)
class SystemValue:
    """What the parser produced for one line, as the scorer needs it."""

    analyte: str
    printed_label: str
    value: float | None
    unit: str
    reference_text: str
    printed_flag: str
    section: str
    #: False when the parser produced the line but refused to stand behind it.
    persists_clinical_value: bool
    status: str = ""
    reason: str = ""

    @property
    def key(self) -> str:
        return self.analyte or f"<unmodelled:{self.printed_label.strip().lower()}>"

    def comparable(self) -> dict[str, str]:
        return {
            "value": "" if self.value is None else f"{self.value:.6g}",
            "unit": self.unit.strip().lower(),
            "reference_text": " ".join(self.reference_text.split()).lower(),
            "printed_flag": self.printed_flag.strip().upper(),
            "section": " ".join(self.section.split()).upper(),
        }


@dataclass(slots=True)
class AttributeScore:
    attribute: str
    correct: int = 0
    wrong: int = 0
    unresolved: int = 0

    @property
    def scored(self) -> int:
        return self.correct + self.wrong

    @property
    def accuracy(self) -> float | None:
        return ratio(self.correct, self.scored)

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.correct, self.scored)

    def as_dict(self) -> dict:
        return {
            "attribute": self.attribute, "scored": self.scored,
            "correct": self.correct, "wrong": self.wrong,
            "accuracy": self.accuracy, "interval": self.interval,
            "unresolved": self.unresolved,
        }


@dataclass(slots=True)
class ExtractionResult:
    corpus_id: str
    documents: int = 0
    # --- detection ---
    found: int = 0
    missed: int = 0
    #: Lines the parser produced that no annotator recorded at all.
    invented: int = 0
    # --- fabrication, the headline ---
    #: Produced, persisted, and the number disagrees with what is printed.
    wrong_value_persisted: int = 0
    #: Produced and persisted for a line the annotators say yields nothing.
    persisted_a_refusable_line: int = 0
    # --- refusal ---
    refusable_lines: int = 0
    correctly_refused: int = 0
    #: Produced but honestly marked as not persistable. Not an error.
    refused_out_loud: int = 0
    # --- document level ---
    document_type_correct: int = 0
    document_type_scored: int = 0
    unreadable_agreed: int = 0
    unreadable_scored: int = 0
    attributes: dict[str, AttributeScore] = field(default_factory=dict)
    documents_with_unresolved_fields: int = 0
    single_annotator_documents: int = 0
    examples_of_fabrication: list[str] = field(default_factory=list)
    confidence_level: float = CONFIDENCE_LEVEL

    @property
    def expected(self) -> int:
        return self.found + self.missed

    @property
    def detection_precision(self) -> float | None:
        return ratio(self.found, self.found + self.invented)

    @property
    def detection_recall(self) -> float | None:
        return ratio(self.found, self.expected)

    @property
    def detection_f1(self) -> float | None:
        return f1(self.detection_precision, self.detection_recall)

    @property
    def fabrications(self) -> int:
        """Values a reader would take as read and that the report does not say."""
        return self.wrong_value_persisted + self.persisted_a_refusable_line

    @property
    def fabrication_rate(self) -> float | None:
        """Over everything the parser persisted. The number that matters."""
        persisted = self.found - self.refused_out_loud + self.persisted_a_refusable_line
        return ratio(self.fabrications, persisted)

    @property
    def refusal_rate(self) -> float | None:
        return ratio(self.correctly_refused, self.refusable_lines)

    @property
    def unresolved_rate(self) -> float:
        if not self.documents:
            return 0.0
        return self.documents_with_unresolved_fields / self.documents

    def as_dict(self) -> dict:
        return {
            "corpus_id": self.corpus_id,
            "documents": self.documents,
            "confidence_level": self.confidence_level,
            "detection": {
                "expected": self.expected, "found": self.found,
                "missed": self.missed, "invented": self.invented,
                "precision": self.detection_precision,
                "precision_interval": wilson_interval(
                    self.found, self.found + self.invented
                ),
                "recall": self.detection_recall,
                "recall_interval": wilson_interval(self.found, self.expected),
                "f1": self.detection_f1,
            },
            "fabrication": {
                "total": self.fabrications,
                "rate": self.fabrication_rate,
                "wrong_value_persisted": self.wrong_value_persisted,
                "persisted_a_refusable_line": self.persisted_a_refusable_line,
                "examples": self.examples_of_fabrication[:20],
            },
            "refusal": {
                "refusable_lines": self.refusable_lines,
                "correctly_refused": self.correctly_refused,
                "rate": self.refusal_rate,
                "refused_out_loud": self.refused_out_loud,
            },
            "document_type_accuracy": ratio(
                self.document_type_correct, self.document_type_scored
            ),
            "unreadable_agreement": ratio(
                self.unreadable_agreed, self.unreadable_scored
            ),
            "attributes": {
                name: score.as_dict()
                for name, score in sorted(self.attributes.items())
            },
            "unresolved_rate": round(self.unresolved_rate, 4),
            "single_annotator_documents": self.single_annotator_documents,
        }


def _gold_field(item: ExtractionItem, key: str) -> tuple[FieldAnnotation | None, LabelSource]:
    """The agreed transcription of one line, or why there isn't one."""
    present = [a.field(key) for a in item.annotations]
    recorded = [f for f in present if f is not None]
    if not recorded:
        return None, LabelSource.NOT_APPLICABLE

    # Agreement is on the whole line: the annotators must have transcribed
    # every attribute the same way, plus the refusal judgement.
    def _token(f: FieldAnnotation) -> str:
        return "|".join(
            [str(f.should_not_be_extracted), *f.comparable().values()]
        )

    ruled = item.adjudication.field(key) if item.adjudication else None
    resolution = resolve(
        key, [_token(f) for f in recorded], _token(ruled) if ruled else None
    )
    if resolution.source is LabelSource.ADJUDICATED:
        return ruled, resolution.source
    if resolution.source is LabelSource.UNANIMOUS:
        return recorded[0], resolution.source
    return None, resolution.source


def score(
    corpus: ExtractionCorpus, outputs: dict[str, list[SystemValue]]
) -> ExtractionResult:
    """Compare what the parser read against what the annotators transcribed."""
    result = ExtractionResult(corpus_id=corpus.corpus_id, documents=len(corpus))
    for name in ATTRIBUTES:
        result.attributes[name] = AttributeScore(attribute=name)

    for item in corpus.items:
        produced = {v.key: v for v in outputs.get(item.document_id, [])}
        if item.annotator_count < 2:
            result.single_annotator_documents += 1

        _score_document_level(result, item, outputs)
        unresolved_here = False

        for key in sorted(item.keys):
            gold, source = _gold_field(item, key)
            if source is LabelSource.UNRESOLVED:
                unresolved_here = True
                for name in ATTRIBUTES:
                    result.attributes[name].unresolved += 1
                produced.pop(key, None)
                continue
            if gold is None:
                continue

            system = produced.pop(key, None)
            if gold.should_not_be_extracted:
                _score_refusal(result, item, gold, system)
            else:
                _score_extraction(result, item, gold, system)

        # Anything the parser produced that no annotator recorded at all.
        for key, system in produced.items():
            result.invented += 1
            if system.persists_clinical_value:
                result.persisted_a_refusable_line += 1
                _remember(result, item, key, "produced a line no annotator recorded")
            else:
                result.refused_out_loud += 1

        if unresolved_here:
            result.documents_with_unresolved_fields += 1

    return result


def _score_document_level(result, item, outputs) -> None:
    types = [a.document_type for a in item.annotations]
    ruled = item.adjudication.document_type if item.adjudication else None
    resolution = resolve("document_type", types, ruled or None)
    if resolution.scoreable:
        result.document_type_scored += 1
        reported = getattr(outputs.get(item.document_id, None), "document_type", None)
        if reported is not None and reported == resolution.agreed:
            result.document_type_correct += 1

    readable = [str(a.readable) for a in item.annotations]
    if resolve("readable", readable, None).scoreable:
        result.unreadable_scored += 1


def _score_extraction(result, item, gold: FieldAnnotation, system) -> None:
    if system is None:
        result.missed += 1
        return

    result.found += 1
    if not system.persists_clinical_value:
        # Produced, and honestly refused. Not a fabrication: refusing out loud
        # is what the status ladder is for. It is still a miss for detection.
        result.refused_out_loud += 1
        return

    gold_attributes = gold.comparable()
    system_attributes = system.comparable()
    for name in ATTRIBUTES:
        if name == "value":
            correct = _same_number(gold.value, system.value)
        else:
            correct = gold_attributes[name] == system_attributes[name]
        entry = result.attributes[name]
        if correct:
            entry.correct += 1
        else:
            entry.wrong += 1

    if not _same_number(gold.value, system.value):
        result.wrong_value_persisted += 1
        _remember(
            result, item, gold.key,
            f"persisted {system.value} where the report prints {gold.value}",
        )


def _score_refusal(result, item, gold: FieldAnnotation, system) -> None:
    result.refusable_lines += 1
    if system is None or not system.persists_clinical_value:
        result.correctly_refused += 1
        if system is not None:
            result.refused_out_loud += 1
        return
    result.persisted_a_refusable_line += 1
    _remember(
        result, item, gold.key,
        f"persisted a value for a line that yields nothing ({gold.why_not})",
    )


def _same_number(gold: float | None, system: float | None) -> bool:
    if gold is None or system is None:
        return gold is None and system is None
    if gold == 0:
        return system == 0
    return abs(system - gold) / abs(gold) <= VALUE_TOLERANCE


def _remember(result: ExtractionResult, item, key: str, detail: str) -> None:
    if len(result.examples_of_fabrication) < 40:
        result.examples_of_fabrication.append(
            f"{item.document_id} / {key}: {detail}"
        )
