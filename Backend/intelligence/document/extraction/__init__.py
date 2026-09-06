"""Stage 6 (Phase 3): pull clinical values out of classified report text.

Not yet implemented. When it is, it takes section-detected text plus the
report's :class:`~intelligence.document.schemas.model.ReportSchema` and returns
candidate :class:`~intelligence.document.schemas.completeness.ExtractedValue`
records, each carrying where it came from - page, section, character span - and
a confidence. It never invents a value it cannot locate in the text, and it
never fills a missing field with a default.
"""
from __future__ import annotations
