"""The medical finding dictionary.

Approved knowledge about each finding: what it means, what it is commonly
associated with, what must not be said about it, and where the statement comes
from. When a language model is eventually added it communicates *this*; it does
not decide any of it, and it may not introduce an association that is not
listed here.

``must_not_say`` is the part that does real work. Eosinophilia is associated
with parasitic infection, so a model asked to explain it will reach for
"parasitic infection" - and a patient reading "you may have a parasite" from a
routine blood count has been harmed by a system that was only trying to be
helpful. The policy for each entry states the bound explicitly.

Entries are grouped by body system in sibling modules, in the same shape as
the detector modules they explain. A detector may not compose its own
explanation: ``build_finding`` raises if a code has no entry here, so adding a
detector without deciding what may be said about it is not possible.
"""
from __future__ import annotations

from intelligence.knowledge.findings import (
    conditions,
    electrolytes,
    hematology,
    hepatic,
    metabolic,
    renal,
    thyroid,
)
from intelligence.knowledge.findings.model import KNOWLEDGE_VERSION, FindingKnowledge

_MODULES = (
    hematology, metabolic, renal, hepatic, thyroid, electrolytes, conditions,
)

_KNOWLEDGE: dict[str, FindingKnowledge] = {}
for _module in _MODULES:
    for _code, _entry in _module.KNOWLEDGE.items():
        if _code in _KNOWLEDGE:
            raise ValueError(
                f"{_code} appears in two knowledge modules. One finding code "
                f"means one approved explanation."
            )
        if _code != _entry.code:
            raise ValueError(f"{_code} is filed under the wrong code ({_entry.code})")
        _KNOWLEDGE[_code] = _entry


def get(code: str) -> FindingKnowledge | None:
    return _KNOWLEDGE.get(code)


def known_codes() -> list[str]:
    return sorted(_KNOWLEDGE)


__all__ = ["FindingKnowledge", "KNOWLEDGE_VERSION", "get", "known_codes"]
