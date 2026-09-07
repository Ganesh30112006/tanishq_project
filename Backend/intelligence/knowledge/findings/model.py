"""The shape of one entry in the medical finding dictionary.

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
"""
from __future__ import annotations

from dataclasses import dataclass, field

KNOWLEDGE_VERSION = "findings-knowledge-1"


@dataclass(frozen=True, slots=True)
class FindingKnowledge:
    code: str
    canonical_name: str
    definition: str
    #: Plain-English sentence a clinician or patient can read. Indian English,
    #: simple words - this is user-facing copy.
    plain_explanation: str
    common_associations: tuple[str, ...] = ()
    must_not_say: tuple[str, ...] = ()
    cautionary_notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    #: What a downstream explainer is permitted to do with this finding.
    explanation_policy: str = (
        "Describe the measurement and its relation to the reference range. Name "
        "possible settings only as possibilities. Never state or imply a "
        "diagnosis. Always say that a doctor must interpret the result."
    )
    next_steps: tuple[str, ...] = field(default_factory=tuple)
