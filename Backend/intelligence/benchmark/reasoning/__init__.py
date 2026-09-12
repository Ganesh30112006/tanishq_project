"""The clinical reasoning benchmark: structured evidence -> finding or condition.

The second of two benchmarks. It is scored against the *annotator's* structured
evidence rather than against what the extraction layer produced, so a reasoning
score measures reasoning: a detector is not penalised for a haemoglobin the
parser misread, and is not credited when good extraction masks an unsafe rule.

Its annotators must be clinicians. Deciding whether a finding is present, what
evidence would have been sufficient, and whether a condition is supported are
clinical judgements; transcribing a printed number is not, which is why the two
corpora are separate.
"""
from __future__ import annotations

from intelligence.benchmark.reasoning.corpus import (
    CorpusError,
    integrity_problems,
    load,
)
from intelligence.benchmark.reasoning.labels import (
    Label,
    LabelSource,
    condition_label,
    disagreements,
    finding_label,
    review_label,
)
from intelligence.benchmark.reasoning.schema import (
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
from intelligence.benchmark.reasoning.scoring import (
    BenchmarkResult,
    CodeScore,
    score,
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
    "ReportAnnotation",
    "condition_label",
    "disagreements",
    "finding_label",
    "integrity_problems",
    "load",
    "review_label",
    "score",
]
