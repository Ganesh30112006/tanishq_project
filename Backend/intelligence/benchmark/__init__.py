"""Two benchmarks, kept apart on purpose.

Every detector this system ships is ``NOT_VALIDATED``. The rules come from
published clinical criteria, which makes each one a *hypothesis* about the
reports this system actually receives - photographed pages from many
laboratories, each with its own reference ranges, spellings and layouts.
Whether a rule written from a textbook holds there is an empirical question,
and nobody has answered it.

But "does the system get this right?" is two questions, and answering them
together answers neither::

    text or image  ──▶  structured evidence     the extraction benchmark
    structured evidence  ──▶  finding/condition  the reasoning benchmark

A detector can have flawless reasoning and be fed a misread haemoglobin.
Extraction can be perfect and feed a rule that draws an unsafe conclusion.
Scored together, those two failures are indistinguishable, and the number they
produce tells nobody which layer to fix. So they are separate corpora, separate
scores and separate promotion gates, and the reasoning benchmark is scored
against the *annotators'* structured evidence rather than the parser's - a
detector is not penalised for a value the parser misread, and is not credited
when good extraction masks an unsafe rule.

The split is cheaper as well as more honest. Transcribing a printed report
accurately is a different skill from judging whether a result is clinically
meaningful, so the extraction corpus does not need clinician time.

    extraction/   schema, loader, scoring for the reading layer
    reasoning/    schema, loader, scoring for the clinical layer
    spec          the frozen definitions every label in both corpora means
    adjudication  several annotators -> the one label a score needs (shared)
    statistics    proportions with intervals that behave at the extremes
    promotion     the two gates, written before there was data to run

**Neither corpus exists in this repository, and neither may be manufactured.**
A file of plausible-looking labels would be indistinguishable from real
annotation a few months from now, and every number computed from it would
inherit that. The tests build their fixtures in memory for exactly this
reason. ``benchmark/README.md`` describes how real corpora are produced.

Run ``python -m intelligence.benchmark`` to see how far off each layer is.
"""
from __future__ import annotations

from intelligence.benchmark import extraction, reasoning
from intelligence.benchmark.adjudication import LabelSource, Resolution, resolve
from intelligence.benchmark.promotion import (
    MAX_FABRICATIONS,
    MIN_CORPUS_REPORTS,
    MIN_EXTRACTION_DOCUMENTS,
    MIN_NEGATIVE_EVENTS,
    MIN_POSITIVE_EVENTS,
    Decision,
    PromotionDecision,
    evaluate,
    evaluate_all,
    evaluate_extraction,
    readiness,
)
from intelligence.benchmark.spec import (
    ANNOTATION_SPEC_VERSION,
    DEFINITIONS,
    Definition,
    check_frozen,
    definition,
    fingerprint,
)
from intelligence.benchmark.statistics import CONFIDENCE_LEVEL, wilson_interval

__all__ = [
    "ANNOTATION_SPEC_VERSION",
    "CONFIDENCE_LEVEL",
    "DEFINITIONS",
    "MAX_FABRICATIONS",
    "MIN_CORPUS_REPORTS",
    "MIN_EXTRACTION_DOCUMENTS",
    "MIN_NEGATIVE_EVENTS",
    "MIN_POSITIVE_EVENTS",
    "Decision",
    "Definition",
    "LabelSource",
    "PromotionDecision",
    "Resolution",
    "check_frozen",
    "definition",
    "evaluate",
    "evaluate_all",
    "evaluate_extraction",
    "extraction",
    "fingerprint",
    "readiness",
    "reasoning",
    "resolve",
    "wilson_interval",
]
