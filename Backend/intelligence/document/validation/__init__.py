"""Stage 8: deterministic checks before a value is trusted.

``validate_value`` applies plausibility bounds, unit acceptance, reference-range
comparison and printed-flag agreement to one extracted value, yielding a
``ValueStatus`` of OBSERVED / NEEDS_REVIEW / REJECTED. No value proposed by OCR
or, later, a language model becomes trusted without passing through here.
"""
from __future__ import annotations

from intelligence.document.validation.checks import ValidatedValue, validate_value

__all__ = ["ValidatedValue", "validate_value"]
