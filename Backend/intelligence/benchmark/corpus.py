"""Reading an annotated corpus off disk, strictly.

Every check here refuses rather than repairs. A corpus that loads is one whose
labels can be trusted to mean what the schema says; a corpus with a
half-answered report is not a slightly worse corpus, it is one where a code
silently drops out of the denominator and the recall it produces is wrong in a
direction nobody can see.

The file format is one JSON document per corpus::

    {
      "corpus_id": "...",
      "description": "...",
      "schema_version": "benchmark-annotation-1",
      "items": [
        {
          "report_id": "...", "report_type": "CBC", "source_sha256": "...",
          "annotations": [ {...}, {...} ],
          "adjudication": { ... }        // optional
        }
      ]
    }
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from intelligence.benchmark.schema import (
    ANNOTATION_SCHEMA_VERSION,
    Adjudication,
    BenchmarkItem,
    ConditionAnnotation,
    ConditionSupport,
    Corpus,
    Determination,
    EvidenceSufficiency,
    FindingAnnotation,
    ReportAnnotation,
)


class CorpusError(ValueError):
    """A corpus file that cannot be trusted to mean what it says."""


def _date(raw: str, *, where: str) -> date:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: {raw!r} is not an ISO date") from exc


def _finding(raw: dict, *, where: str) -> FindingAnnotation:
    try:
        return FindingAnnotation(
            code=raw["code"],
            determination=Determination(raw["determination"]),
            evidence_sufficient=EvidenceSufficiency(raw["evidence_sufficient"]),
            alternative_explanation=raw.get("alternative_explanation", ""),
            note=raw.get("note", ""),
        )
    except (KeyError, ValueError) as exc:
        raise CorpusError(f"{where}: bad finding annotation - {exc}") from exc


def _condition(raw: dict, *, where: str) -> ConditionAnnotation:
    try:
        return ConditionAnnotation(
            code=raw["code"],
            support=ConditionSupport(raw["support"]),
            alternative_explanation=raw.get("alternative_explanation", ""),
            note=raw.get("note", ""),
        )
    except (KeyError, ValueError) as exc:
        raise CorpusError(f"{where}: bad condition annotation - {exc}") from exc


def _annotation(raw: dict, *, where: str) -> ReportAnnotation:
    try:
        return ReportAnnotation(
            report_id=raw["report_id"],
            report_type=raw["report_type"],
            annotator_id=raw["annotator_id"],
            annotated_on=_date(raw["annotated_on"], where=where),
            applicable_finding_codes=tuple(raw.get("applicable_finding_codes", ())),
            applicable_condition_codes=tuple(
                raw.get("applicable_condition_codes", ())
            ),
            findings=tuple(
                _finding(f, where=where) for f in raw.get("findings", ())
            ),
            conditions=tuple(
                _condition(c, where=where) for c in raw.get("conditions", ())
            ),
            human_review_required=bool(raw["human_review_required"]),
            supporting_evidence=tuple(raw.get("supporting_evidence", ())),
            missing_evidence=tuple(raw.get("missing_evidence", ())),
            schema_version=raw.get("schema_version", ANNOTATION_SCHEMA_VERSION),
            note=raw.get("note", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: bad annotation - {exc}") from exc


def _adjudication(raw: dict | None, *, where: str) -> Adjudication | None:
    if raw is None:
        return None
    try:
        return Adjudication(
            adjudicator_id=raw["adjudicator_id"],
            adjudicated_on=_date(raw["adjudicated_on"], where=where),
            findings=tuple(_finding(f, where=where) for f in raw.get("findings", ())),
            conditions=tuple(
                _condition(c, where=where) for c in raw.get("conditions", ())
            ),
            disagreement_reason=raw.get("disagreement_reason", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: bad adjudication - {exc}") from exc


def _item(raw: dict) -> BenchmarkItem:
    where = f"report {raw.get('report_id', '?')!r}"
    try:
        return BenchmarkItem(
            report_id=raw["report_id"],
            report_type=raw["report_type"],
            source_sha256=raw["source_sha256"],
            annotations=tuple(
                _annotation(a, where=where) for a in raw["annotations"]
            ),
            adjudication=_adjudication(raw.get("adjudication"), where=where),
            note=raw.get("note", ""),
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{where}: {exc}") from exc


def load(path: str | Path) -> Corpus:
    """Read and fully validate a corpus file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"{path}: {exc}") from exc

    version = raw.get("schema_version", ANNOTATION_SCHEMA_VERSION)
    if version != ANNOTATION_SCHEMA_VERSION:
        raise CorpusError(
            f"{path}: annotated under {version}, this code speaks "
            f"{ANNOTATION_SCHEMA_VERSION}"
        )
    try:
        return Corpus(
            corpus_id=raw["corpus_id"],
            description=raw.get("description", ""),
            items=[_item(item) for item in raw.get("items", [])],
            schema_version=version,
        )
    except CorpusError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise CorpusError(f"{path}: {exc}") from exc


def integrity_problems(corpus: Corpus) -> list[str]:
    """Things that do not stop the file loading but weaken what it can say."""
    problems: list[str] = []
    for item in corpus.items:
        if item.annotator_count < 2:
            problems.append(
                f"{item.report_id}: read by {item.annotator_count} clinician, "
                f"so a single reader's habits would become the ground truth"
            )
        if not item.source_sha256:
            problems.append(
                f"{item.report_id}: no source hash, so the annotation cannot "
                f"be tied to the document that was read"
            )
        if not item.applicable_finding_codes and not item.applicable_condition_codes:
            problems.append(
                f"{item.report_id}: no code was scoped to it, so it "
                f"contributes nothing to any measurement"
            )
    return problems
