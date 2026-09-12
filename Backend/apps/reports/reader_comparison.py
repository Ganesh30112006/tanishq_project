"""Comparing the two readers, and recording where they differed.

Shadow mode exists for this. Calling the service and storing what it said
proves only that it answers; what has to be known before it may influence a
clinical outcome is *where the two readers disagree on real reports, and which
of them is right*. That question is answered by a person looking at a document,
so the job of this module is to find the disagreements, preserve enough of each
one to adjudicate it, and stop there.

Two things it deliberately does not do.

**It does not score agreement.** Two readers can agree and both be wrong, so an
agreement percentage is a comfort, not a measurement. What is counted here are
kinds of disagreement, each kept with its example.

**It does not decide who was wrong.** The taxonomy this record exists to fill
in - SAFE_IMPROVEMENT, PARSER_ERROR, NORMALIZATION_ERROR, OLD_READER_ERROR and
the rest - cannot be settled from two outputs. Both readers produce a number;
neither produces the truth. Only three classes follow from the responses
themselves:

``SAFE_ABSTENTION``     the second reader produced no value it would stand
                        behind, and said why. Safe by construction: in every
                        mode an abstention can only hold a report, never
                        release one. Whether it *should* have read the line is
                        still open, and a reviewer may re-classify it.
``CONFLICT_DETECTION``  the second reader found the same analyte printed twice
                        with results that disagree after conversion.
``OCR_FAILURE``         the text could not be recovered at all.

Everything else is left ``UNKNOWN``. An automatic guess would fill the table
with labels nobody made, and the table's only purpose is to hold labels
somebody did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.common.enums import ReportProcessingState
from apps.reports.models import ReaderComparison, ReaderDisagreement

Kind = ReaderDisagreement.Kind
Classification = ReaderDisagreement.Classification

#: How close two numbers must be to count as the same reading. Loose enough to
#: absorb the last printed digit, tight enough that a misread stands out.
VALUE_TOLERANCE = Decimal("0.0001")

#: Dispositions from the service that mean it wants a person to look.
_HOLDING_DISPOSITIONS = frozenset({"NEEDS_REVIEW", "UNREADABLE", "REJECTED_FILE"})


@dataclass(slots=True)
class Difference:
    """One place the readers differed, before it reaches the database."""

    kind: str
    analyte: str = ""
    existing_value: str = ""
    existing_unit: str = ""
    existing_state: str = ""
    second_value: str = ""
    second_unit: str = ""
    second_status: str = ""
    second_reason: str = ""
    second_persistable: bool = False
    printed_label: str = ""
    excerpt: str = ""
    classification: str = Classification.UNKNOWN
    classified_by: str = ""


@dataclass(slots=True)
class Comparison:
    """The whole comparison for one report."""

    existing_outcome: str
    second_disposition: str = ""
    second_available: bool = False
    unavailable_reason: str = ""
    existing_value_count: int = 0
    second_value_count: int = 0
    differences: list[Difference] = field(default_factory=list)

    @property
    def agreed(self) -> bool:
        return self.second_available and not self.differences


def compare(*, existing_outcome: str, tests, opinion) -> Comparison:
    """Line up what the pipeline read against what the service read.

    ``tests`` are the ``ReportTest`` rows the pipeline produced; ``opinion`` is
    the :class:`apps.reports.second_reader.SecondOpinion`. Pure: it reads both
    sides and returns the differences without touching the database.
    """
    comparison = Comparison(
        existing_outcome=existing_outcome,
        second_disposition=opinion.disposition,
        second_available=opinion.available,
        unavailable_reason=opinion.unavailable_reason,
        existing_value_count=len(tests),
    )
    if not opinion.available:
        # No opinion is not a disagreement. It is recorded so the silence is
        # visible in the record rather than looking like agreement.
        return comparison

    second_values = list(opinion.values)
    comparison.second_value_count = len(second_values)

    if opinion.disposition == "UNREADABLE":
        comparison.differences.append(Difference(
            kind=Kind.DOCUMENT_UNREADABLE,
            second_status="UNREADABLE",
            second_reason="the second reader could not recover the text",
            classification=Classification.OCR_FAILURE,
            classified_by="observed",
        ))

    by_analyte = _index(second_values)
    seen: set[str] = set()

    for test in tests:
        analyte = (test.name or "").strip().lower()
        seen.add(analyte)
        theirs = by_analyte.get(analyte)
        if theirs is None:
            comparison.differences.append(Difference(
                kind=Kind.ONLY_EXISTING,
                analyte=test.name,
                existing_value=str(test.value_raw or ""),
                existing_unit=test.unit_raw or "",
                existing_state=test.state or "",
                second_reason="the second reader did not report this analyte",
            ))
            continue
        difference = _compare_one(test, theirs)
        if difference is not None:
            comparison.differences.append(difference)

    for analyte, theirs in sorted(by_analyte.items()):
        if analyte in seen:
            continue
        comparison.differences.append(Difference(
            kind=Kind.ONLY_SECOND,
            analyte=theirs.get("analyte") or "",
            second_value=_text(theirs.get("value")),
            second_unit=theirs.get("unit") or "",
            second_status=theirs.get("status") or "",
            second_reason=theirs.get("reason") or "",
            second_persistable=bool(theirs.get("persists_clinical_value")),
            printed_label=theirs.get("printed_label") or "",
            excerpt=_excerpt(theirs),
            **_observed_class(theirs),
        ))

    existing_holds = existing_outcome != ReportProcessingState.FINALIZED
    second_holds = (
        opinion.disposition in _HOLDING_DISPOSITIONS or bool(opinion.concerns)
    )
    if existing_holds != second_holds:
        comparison.differences.append(Difference(
            kind=Kind.ROUTING_DIFFERS,
            existing_state=existing_outcome,
            second_status=opinion.disposition,
            second_reason=(
                "; ".join(opinion.concerns)[:120] if opinion.concerns
                else "the second reader raised no concern"
            ),
        ))
    return comparison


def _compare_one(test, theirs: dict) -> Difference | None:
    persistable = bool(theirs.get("persists_clinical_value"))
    base = {
        "analyte": test.name,
        "existing_value": str(test.value_raw or ""),
        "existing_unit": test.unit_raw or "",
        "existing_state": test.state or "",
        "second_value": _text(theirs.get("value")),
        "second_unit": theirs.get("unit") or "",
        "second_status": theirs.get("status") or "",
        "second_reason": theirs.get("reason") or "",
        "second_persistable": persistable,
        "printed_label": theirs.get("printed_label") or "",
        "excerpt": _excerpt(theirs),
    }

    if not persistable:
        # The second reader read something and would not stand behind it. That
        # is a difference worth keeping even though it changes nothing: it is
        # either a line the existing pipeline should not have trusted, or a
        # line the new parser should have read. Which one is a human question.
        return Difference(kind=Kind.NOT_PERSISTABLE, **base, **_observed_class(theirs))

    ours = _decimal(test.value_raw)
    mine_normalized = test.value_normalized
    theirs_value = _decimal(theirs.get("value"))
    theirs_normalized = _decimal((theirs.get("normalized") or {}).get("value"))

    if ours is not None and theirs_value is not None:
        if abs(ours - theirs_value) > VALUE_TOLERANCE:
            # Different printed numbers. If both normalise to the same thing
            # the readers agree about the measurement and differ about the
            # unit, which is a different problem with a different fix.
            if (
                mine_normalized is not None
                and theirs_normalized is not None
                and abs(Decimal(mine_normalized) - theirs_normalized) <= VALUE_TOLERANCE
            ):
                return Difference(kind=Kind.UNIT_DIFFERS, **base)
            return Difference(kind=Kind.VALUE_DIFFERS, **base)

    their_unit = (theirs.get("unit") or "").strip().lower()
    our_unit = (test.unit_raw or "").strip().lower()
    if their_unit and our_unit and their_unit != our_unit:
        return Difference(kind=Kind.UNIT_DIFFERS, **base)
    return None


def _observed_class(theirs: dict) -> dict:
    """The only classes that follow from the response itself."""
    status = (theirs.get("status") or "").upper()
    if status == "CONFLICTING":
        return {
            "classification": Classification.CONFLICT_DETECTION,
            "classified_by": "observed",
        }
    if status == "UNREADABLE":
        return {
            "classification": Classification.OCR_FAILURE,
            "classified_by": "observed",
        }
    if not theirs.get("persists_clinical_value") and theirs.get("reason"):
        return {
            "classification": Classification.SAFE_ABSTENTION,
            "classified_by": "observed",
        }
    return {}


def _index(values: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for value in values:
        key = (value.get("analyte") or "").strip().lower()
        if not key:
            continue
        # A second occurrence is the service's own conflict detection, which it
        # reports as a status on the value; keeping the first is enough here.
        out.setdefault(key, value)
    return out


def _decimal(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _text(raw) -> str:
    return "" if raw is None else str(raw)[:64]


def _excerpt(theirs: dict) -> str:
    source = (theirs.get("provenance") or {}).get("source_text") or ""
    return " ".join(str(source).split())[:300]


def record(report, comparison: Comparison, *, mode: str) -> ReaderComparison | None:
    """Persist the comparison. Never raises.

    Called from the report pipeline, which must not fail because a research
    record could not be written. A comparison that cannot be stored is a lost
    observation, not a lost report.
    """
    try:
        row = ReaderComparison.objects.create(
            report=report,
            mode=mode,
            existing_outcome=comparison.existing_outcome,
            second_disposition=comparison.second_disposition,
            second_available=comparison.second_available,
            unavailable_reason=comparison.unavailable_reason[:200],
            existing_value_count=comparison.existing_value_count,
            second_value_count=comparison.second_value_count,
            agreed=comparison.agreed,
            detail={"differences": len(comparison.differences)},
        )
        ReaderDisagreement.objects.bulk_create([
            ReaderDisagreement(
                comparison=row,
                analyte=d.analyte[:120],
                kind=d.kind,
                existing_value=d.existing_value[:64],
                existing_unit=d.existing_unit[:32],
                existing_state=d.existing_state[:16],
                second_value=d.second_value[:64],
                second_unit=d.second_unit[:32],
                second_status=d.second_status[:16],
                second_reason=d.second_reason[:120],
                second_persistable=d.second_persistable,
                printed_label=d.printed_label[:200],
                excerpt=d.excerpt[:300],
                classification=d.classification,
                classified_by=d.classified_by[:120],
                classified_at=timezone.now() if d.classified_by else None,
            )
            for d in comparison.differences
        ])
        return row
    except Exception:  # noqa: BLE001 - see the docstring
        return None


def classify(
    disagreement: ReaderDisagreement, *, as_class: str, by: str, note: str = ""
) -> ReaderDisagreement:
    """Record a person's ruling on one disagreement.

    A ruling needs a named reviewer and a reason. The reason is the part worth
    having: the counts say how often the readers differ, and only the written
    reasons say what to change.
    """
    if as_class not in Classification.values:
        raise ValueError(
            f"{as_class!r} is not one of {sorted(Classification.values)}"
        )
    if as_class == Classification.UNKNOWN:
        raise ValueError(
            "UNKNOWN is what a disagreement starts as, not something a "
            "reviewer concludes. If it cannot be decided, leave it and say so "
            "in the note."
        )
    if not by.strip():
        raise ValueError("a classification needs a named reviewer")
    if not note.strip():
        raise ValueError(
            "a classification needs a reason. The counts are already known; "
            "the reason is the only part that says what to fix."
        )
    disagreement.classification = as_class
    disagreement.classified_by = by.strip()[:120]
    disagreement.classification_note = note.strip()
    disagreement.classified_at = timezone.now()
    disagreement.save(update_fields=[
        "classification", "classified_by", "classification_note",
        "classified_at", "updated_at",
    ])
    return disagreement
