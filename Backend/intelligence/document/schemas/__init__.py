"""Stage 5: what a report of each type is expected to contain.

The schema for a report type lists its fields - which are required, what they
may be called, what units are acceptable, and the plausibility bounds a value
must fall within. :func:`assess_completeness` compares an extracted report
against its schema and returns one of ``COMPLETE / INCOMPLETE / AMBIGUOUS /
INVALID / CONFLICTING``.

These definitions are data, not code buried in the OCR or extraction layer, so
a clinician can review and change them without touching a parser. The
plausibility bounds are kept aligned with ``apps.reports.default_schemas`` so
the two layers cannot disagree about what counts as an impossible value.
"""
from __future__ import annotations

from intelligence.document.schemas.completeness import (
    CompletenessReport,
    ExtractedValue,
    FieldOutcome,
    assess_completeness,
)
from intelligence.document.schemas.model import ReportFieldSpec, ReportSchema
from intelligence.document.schemas.registry import get_schema, known_schema_types

__all__ = [
    "ReportFieldSpec",
    "ReportSchema",
    "get_schema",
    "known_schema_types",
    "ExtractedValue",
    "FieldOutcome",
    "CompletenessReport",
    "assess_completeness",
]
