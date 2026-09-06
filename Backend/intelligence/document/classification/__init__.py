"""Stage 4: decide what kind of report this is, before extracting anything.

Extraction rules are per report type. Running lipid-panel rules over a
discharge summary produces confident nonsense, so classification comes first
and is allowed to answer "not sure" - :class:`ClassificationStatus.REVIEW_REQUIRED`
with no type - rather than picking the least-wrong option.
"""
from __future__ import annotations

from intelligence.document.classification.keyword import classify

__all__ = ["classify"]
