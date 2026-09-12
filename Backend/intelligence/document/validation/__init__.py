"""Stage 8: deterministic checks before a value is trusted.

``validate_value`` applies plausibility bounds, unit acceptance,
reference-range comparison, printed-flag agreement and an OCR confidence floor
to one extracted value, yielding a ``ValueStatus``. No value proposed by OCR
or, later, a language model becomes trusted without passing through here.

The statuses are different *kinds* of answer, not severity levels. Exactly one
of them - ``OBSERVED`` - means a clinical value may be persisted; every other
says which reason it may not. That distinction is what makes the
no-fabrication guarantee observable rather than merely intended, and
``tests/document/adversarial/`` exists to keep it honest.
"""
from __future__ import annotations

from intelligence.document.validation.checks import (
    OCR_CONFIDENCE_FLOOR,
    ValidatedValue,
    validate_value,
)

__all__ = ["OCR_CONFIDENCE_FLOOR", "ValidatedValue", "validate_value"]
