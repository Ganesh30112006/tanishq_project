"""Stage 7 (Phase 3): canonicalise terminology and units.

Not yet implemented. Maps analyte aliases to canonical names and converts
values to the schema's canonical unit using an explicit, versioned rule set -
the same ``apps.common.units`` rules the Django pipeline uses, so a value
normalised here and one normalised there agree. A unit it does not have a rule
for is left raw and flagged, never guessed.
"""
from __future__ import annotations
