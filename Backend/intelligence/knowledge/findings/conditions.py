"""Approved knowledge for the level-3 condition likelihoods.

See the package docstring for what each field is for and why
``must_not_say`` is the part that does real work.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "POSSIBLE_IRON_DEFICIENCY_ANEMIA": FindingKnowledge(
        code="POSSIBLE_IRON_DEFICIENCY_ANEMIA",
        canonical_name="Pattern that may suggest iron-deficiency anaemia",
        definition=(
            "A low haemoglobin together with small red cells and/or a low "
            "ferritin. This is a pattern, not a diagnosis."
        ),
        plain_explanation=(
            "Your results show a low haemoglobin along with other findings that "
            "can occur in iron deficiency. This is only a possibility. Other "
            "conditions produce the same pattern, and a doctor needs to confirm "
            "the cause before any treatment."
        ),
        common_associations=("low dietary iron", "blood loss including heavy "
                             "periods and gut bleeding", "poor absorption"),
        must_not_say=(
            "Do not state that the patient has iron deficiency.",
            "Do not recommend iron supplements - iron given for the wrong cause "
            "is harmful, and unexplained iron deficiency in an adult needs the "
            "source of blood loss investigated.",
        ),
        cautionary_notes=(
            "Ferritin rises with inflammation and can look normal in a person "
            "who is genuinely iron deficient.",
            "Thalassaemia trait produces a very similar blood-count picture.",
        ),
        aliases=("iron deficiency pattern",),
    ),
}
