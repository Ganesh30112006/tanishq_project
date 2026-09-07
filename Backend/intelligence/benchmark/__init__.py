"""The clinician-annotated gold standard, and the gate it guards.

Every detector this system ships is ``NOT_VALIDATED``. The rules are taken
from published clinical criteria, which makes each one a *hypothesis* about
the reports this system actually receives - photographed pages from many
different laboratories, with their own reference ranges, their own spellings
and their own layouts. Whether a rule written from a textbook holds there is
an empirical question, and nobody has answered it.

This package is the apparatus for answering it, built before there is any data
to put through it. That ordering is deliberate: a threshold chosen after
seeing the numbers is not a threshold, it is a description.

    schema.py     what a clinician is asked, and the shape of the answer
    corpus.py     reading an annotated set off disk, strictly
    labels.py     several clinicians' answers -> the one label a score needs
    scoring.py    precision, recall, F1, abstention, with real intervals
    promotion.py  when a detector may stop calling itself NOT_VALIDATED

**There is no corpus in this repository, and there must not be a manufactured
one.** A file of plausible-looking labels would be indistinguishable from
clinician-annotated data a few months from now, and every number computed from
it would inherit that. The tests build their fixtures in memory for exactly
this reason. `benchmark/README.md` describes how a real corpus is produced.

Run ``python -m intelligence.benchmark`` to see how far off promotion the
system currently is. Today the honest answer is: no corpus, so nothing is
measurable, so every detector correctly still says it has never been measured.
"""
from __future__ import annotations

from intelligence.benchmark.corpus import CorpusError, integrity_problems, load
from intelligence.benchmark.labels import (
    Label,
    LabelSource,
    condition_label,
    disagreements,
    finding_label,
)
from intelligence.benchmark.promotion import (
    MIN_CORPUS_REPORTS,
    MIN_NEGATIVE_EVENTS,
    MIN_POSITIVE_EVENTS,
    PromotionDecision,
    evaluate,
    evaluate_all,
    readiness,
)
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
from intelligence.benchmark.scoring import (
    BenchmarkResult,
    CodeScore,
    score,
    wilson_interval,
)

__all__ = [
    "ANNOTATION_SCHEMA_VERSION",
    "Adjudication",
    "BenchmarkItem",
    "BenchmarkResult",
    "CodeScore",
    "ConditionAnnotation",
    "ConditionSupport",
    "Corpus",
    "CorpusError",
    "Determination",
    "EvidenceSufficiency",
    "FindingAnnotation",
    "Label",
    "LabelSource",
    "MIN_CORPUS_REPORTS",
    "MIN_NEGATIVE_EVENTS",
    "MIN_POSITIVE_EVENTS",
    "PromotionDecision",
    "ReportAnnotation",
    "condition_label",
    "disagreements",
    "evaluate",
    "evaluate_all",
    "finding_label",
    "integrity_problems",
    "load",
    "readiness",
    "score",
    "wilson_interval",
]
