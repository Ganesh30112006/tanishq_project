"""Stage 8 (Phase 3): deterministic checks before anything is trusted.

Not yet implemented. Applies plausibility bounds, cross-field consistency and
schema completeness, producing the final per-value status. No value proposed by
OCR or, later, a language model becomes trusted until it passes here.
"""
from __future__ import annotations
