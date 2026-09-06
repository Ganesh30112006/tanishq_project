"""Approved clinical knowledge, kept out of the code that uses it.

Two tables, both data rather than logic so a clinician can review and change
them without touching a detector:

``reference_ranges``
    Fallback intervals for when a report prints none, separating a population
    *reference interval* from a guideline *decision threshold*.

``findings``
    What each finding means, what it is commonly associated with, and - the
    part that does the work - what must never be said about it.

A language model, when one is added, communicates what is here. It does not
decide any of it and may not introduce an association this dictionary does not
list.
"""
from __future__ import annotations

from intelligence.knowledge import findings, reference_ranges
from intelligence.knowledge.findings import (
    KNOWLEDGE_VERSION,
    FindingKnowledge,
)
from intelligence.knowledge.reference_ranges import RANGE_TABLE_VERSION, Interval

__all__ = [
    "findings",
    "reference_ranges",
    "FindingKnowledge",
    "KNOWLEDGE_VERSION",
    "Interval",
    "RANGE_TABLE_VERSION",
]
