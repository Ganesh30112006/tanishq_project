"""The extraction benchmark: text or image -> structured evidence.

The first of two benchmarks, and it answers only "did we read it correctly?".
It is kept apart from the clinical reasoning benchmark because a detector can
have flawless reasoning and be fed a misread haemoglobin, and extraction can be
perfect while feeding a detector that draws an unsafe conclusion. Scored
together those two failures are indistinguishable, and the one number they
produce tells nobody which layer to fix.

Its annotators need not be clinicians: transcribing a printed report accurately
is a different skill from deciding whether a result is clinically meaningful,
and asking for the two separately makes both corpora cheaper to produce.
"""
from __future__ import annotations

from intelligence.benchmark.extraction.corpus import (
    CorpusError,
    integrity_problems,
    load,
    system_values,
)
from intelligence.benchmark.extraction.schema import (
    EXTRACTION_SCHEMA_VERSION,
    VALUE_TOLERANCE,
    DocumentAnnotation,
    ExtractionAdjudication,
    ExtractionCorpus,
    ExtractionItem,
    FieldAnnotation,
)
from intelligence.benchmark.extraction.scoring import (
    ATTRIBUTES,
    AttributeScore,
    ExtractionResult,
    SystemValue,
    score,
)

__all__ = [
    "ATTRIBUTES",
    "EXTRACTION_SCHEMA_VERSION",
    "VALUE_TOLERANCE",
    "AttributeScore",
    "CorpusError",
    "DocumentAnnotation",
    "ExtractionAdjudication",
    "ExtractionCorpus",
    "ExtractionItem",
    "ExtractionResult",
    "FieldAnnotation",
    "SystemValue",
    "integrity_problems",
    "load",
    "score",
    "system_values",
]
