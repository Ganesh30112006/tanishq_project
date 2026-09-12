"""Reading an extraction corpus off disk, and turning pipeline output into
something the scorer can compare against it.

Both directions are here because they are the same contract read twice: the
annotator writes down analyte, value, unit, printed range, flag and section,
and the pipeline produces exactly those. Keeping the adapter beside the loader
makes a drift between them obvious.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from intelligence.benchmark.extraction.schema import (
    EXTRACTION_SCHEMA_VERSION,
    DocumentAnnotation,
    ExtractionAdjudication,
    ExtractionCorpus,
    ExtractionItem,
    FieldAnnotation,
)
from intelligence.benchmark.extraction.scoring import SystemValue


class CorpusError(ValueError):
    """A corpus file that cannot be trusted to mean what it says."""


def _date(raw: str, *, where: str) -> date:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: {raw!r} is not an ISO date") from exc


def _field(raw: dict, *, where: str) -> FieldAnnotation:
    try:
        return FieldAnnotation(
            analyte=raw.get("analyte", ""),
            printed_label=raw["printed_label"],
            value=raw.get("value"),
            unit=raw.get("unit", ""),
            reference_text=raw.get("reference_text", ""),
            printed_flag=raw.get("printed_flag", ""),
            section=raw.get("section", ""),
            should_not_be_extracted=bool(raw.get("should_not_be_extracted", False)),
            why_not=raw.get("why_not", ""),
            note=raw.get("note", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: bad field annotation - {exc}") from exc


def _annotation(raw: dict, *, where: str) -> DocumentAnnotation:
    try:
        return DocumentAnnotation(
            document_id=raw["document_id"],
            annotator_id=raw["annotator_id"],
            annotated_on=_date(raw["annotated_on"], where=where),
            document_type=raw["document_type"],
            fields=tuple(_field(f, where=where) for f in raw.get("fields", ())),
            readable=bool(raw.get("readable", True)),
            schema_version=raw.get("schema_version", EXTRACTION_SCHEMA_VERSION),
            note=raw.get("note", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: bad annotation - {exc}") from exc


def _adjudication(raw: dict | None, *, where: str) -> ExtractionAdjudication | None:
    if raw is None:
        return None
    try:
        return ExtractionAdjudication(
            adjudicator_id=raw["adjudicator_id"],
            adjudicated_on=_date(raw["adjudicated_on"], where=where),
            document_type=raw.get("document_type", ""),
            fields=tuple(_field(f, where=where) for f in raw.get("fields", ())),
            disagreement_reason=raw.get("disagreement_reason", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: bad adjudication - {exc}") from exc


def _item(raw: dict) -> ExtractionItem:
    where = f"document {raw.get('document_id', '?')!r}"
    try:
        return ExtractionItem(
            document_id=raw["document_id"],
            source_sha256=raw["source_sha256"],
            annotations=tuple(
                _annotation(a, where=where) for a in raw["annotations"]
            ),
            adjudication=_adjudication(raw.get("adjudication"), where=where),
            capture=raw.get("capture", ""),
            note=raw.get("note", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: {exc}") from exc


def load(path: str | Path) -> ExtractionCorpus:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{path}: {exc}") from exc

    version = raw.get("schema_version", EXTRACTION_SCHEMA_VERSION)
    if version != EXTRACTION_SCHEMA_VERSION:
        raise CorpusError(
            f"{path}: annotated under {version}, this code speaks "
            f"{EXTRACTION_SCHEMA_VERSION}"
        )
    try:
        return ExtractionCorpus(
            corpus_id=raw["corpus_id"],
            description=raw.get("description", ""),
            items=[_item(item) for item in raw.get("items", [])],
            schema_version=version,
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{path}: {exc}") from exc


def integrity_problems(corpus: ExtractionCorpus) -> list[str]:
    problems: list[str] = []
    for item in corpus.items:
        if item.annotator_count < 2:
            problems.append(
                f"{item.document_id}: read by {item.annotator_count} annotator, "
                f"so one person's transcription would become the ground truth"
            )
        if not item.source_sha256:
            problems.append(
                f"{item.document_id}: no source hash, so the annotation cannot "
                f"be tied to the document that was read"
            )
        if not any(a.refusable for a in item.annotations):
            problems.append(
                f"{item.document_id}: no line is marked as yielding nothing. "
                f"Most of a report is not a result, and a corpus that records "
                f"only the results cannot measure whether the parser invents "
                f"any."
            )
    return problems


def system_values(result) -> list[SystemValue]:
    """Turn a ``DocumentResult`` into what the extraction scorer compares.

    The adapter lives here rather than in the pipeline so that the benchmark
    depends on the pipeline and never the other way round.
    """
    out: list[SystemValue] = []
    for record in result.values:
        value = record.value
        out.append(SystemValue(
            analyte=value.analyte or "",
            printed_label=value.printed_label,
            value=value.value,
            unit=value.unit,
            reference_text=value.reference.text,
            printed_flag=value.printed_flag,
            section=record.provenance.section if record.provenance else "",
            persists_clinical_value=value.status.persists_clinical_value,
            status=value.status.value,
            reason=value.reason,
        ))
    return out
