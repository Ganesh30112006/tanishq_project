"""Approved knowledge for the electrolyte patterns.

Electrolytes are the one place in this system where a number can be an
emergency, and also the place where a wrong number is commonest. A haemolysed
sample, a drip running into the same arm, a tourniquet left on too long and a
tube left standing overnight each produce a result that looks alarming and is
an artefact.

So every entry here says two things at once: this may matter urgently, and
this may not be real. Neither half may be dropped. Telling a patient their
potassium is dangerous when the sample was haemolysed causes real harm, and so
does saying nothing when it was not.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

_POLICY = (
    "Describe the measurement and its relation to the reference range, and "
    "say plainly that electrolyte results are frequently affected by how the "
    "sample was taken and handled. Do not name a cause, do not estimate "
    "urgency, and do not suggest any treatment, supplement or dietary change. "
    "Always say a doctor must interpret the result, and that a repeat sample "
    "is often needed."
)
_SAMPLE_NOTE = (
    "How the sample was taken and handled changes these numbers. A repeat on "
    "a fresh sample is often what settles whether the result is real."
)

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "HYPONATREMIA_PATTERN": FindingKnowledge(
        code="HYPONATREMIA_PATTERN",
        canonical_name="Low sodium",
        definition="Serum sodium below the reference interval.",
        plain_explanation=(
            "Your sodium is lower than the normal range. Sodium is a salt that "
            "the body keeps in a narrow band, and the level depends as much on "
            "how much water is in the body as on how much salt. A doctor "
            "should review this result."
        ),
        common_associations=(
            "water tablets and several other common medicines",
            "drinking a large amount of water", "heart, liver or kidney "
            "conditions", "hormone conditions", "vomiting or diarrhoea",
        ),
        must_not_say=(
            "Do not name a cause, and do not mention any specific hormone or "
            "organ condition.",
            "Do not advise taking salt or restricting fluid. Correcting sodium "
            "too quickly is dangerous, which is why it is a doctor's decision.",
            "Do not tell the patient whether this is an emergency.",
        ),
        cautionary_notes=(
            _SAMPLE_NOTE,
            "A very high blood sugar or a very high blood fat level makes the "
            "sodium read falsely low on some analysers.",
        ),
        aliases=("low sodium", "hyponatraemia"),
        explanation_policy=_POLICY,
        next_steps=("Show this report to your doctor.",),
    ),
    "HYPERNATREMIA_PATTERN": FindingKnowledge(
        code="HYPERNATREMIA_PATTERN",
        canonical_name="High sodium",
        definition="Serum sodium above the reference interval.",
        plain_explanation=(
            "Your sodium is higher than the normal range. This usually "
            "reflects not having enough water in the body rather than too much "
            "salt. A doctor should review this result."
        ),
        common_associations=(
            "not drinking enough water", "fluid lost through fever, vomiting "
            "or diarrhoea", "some medicines", "hormone conditions",
        ),
        must_not_say=(
            "Do not name a cause.",
            "Do not advise how much water to drink. Correcting sodium too "
            "quickly is dangerous.",
        ),
        cautionary_notes=(_SAMPLE_NOTE,),
        aliases=("high sodium", "hypernatraemia"),
        explanation_policy=_POLICY,
    ),
    "HYPOKALEMIA_PATTERN": FindingKnowledge(
        code="HYPOKALEMIA_PATTERN",
        canonical_name="Low potassium",
        definition="Serum potassium below the reference interval.",
        plain_explanation=(
            "Your potassium is lower than the normal range. Potassium is "
            "needed for muscles and for the heart. A doctor should review this "
            "result."
        ),
        common_associations=(
            "water tablets", "vomiting or diarrhoea", "some other medicines",
            "hormone conditions", "low magnesium",
        ),
        must_not_say=(
            "Do not tell the patient to eat bananas or take a potassium "
            "supplement. Potassium replacement is prescribed and monitored, "
            "and the wrong amount is dangerous.",
            "Do not mention effects on the heart. That is frightening, it is "
            "not something a number alone establishes, and it is the doctor's "
            "to raise.",
            "Do not advise stopping any medicine.",
        ),
        cautionary_notes=(_SAMPLE_NOTE,),
        aliases=("low potassium", "hypokalaemia"),
        explanation_policy=_POLICY,
    ),
    "HYPERKALEMIA_PATTERN": FindingKnowledge(
        code="HYPERKALEMIA_PATTERN",
        canonical_name="High potassium",
        definition="Serum potassium above the reference interval.",
        plain_explanation=(
            "Your potassium is higher than the normal range. A high reading is "
            "often caused by the blood sample itself rather than by the "
            "patient, so this is usually checked on a fresh sample. A doctor "
            "should review this result."
        ),
        common_associations=(
            "a haemolysed sample, where red cells break and release potassium",
            "a tight tourniquet or a difficult blood draw",
            "several common blood pressure medicines",
            "reduced kidney function", "potassium supplements",
        ),
        must_not_say=(
            "Do not mention effects on the heart or describe the result as "
            "dangerous. A high potassium is far more often an artefact of the "
            "sample than a real finding, and alarming a patient over a "
            "haemolysed tube is a real harm.",
            "Do not advise stopping any medicine.",
            "Do not name a kidney condition.",
        ),
        cautionary_notes=(
            "Haemolysis is the single commonest cause of a raised potassium on "
            "a routine sample. Many laboratories flag it; if this report does "
            "not, that does not mean the sample was clean.",
            _SAMPLE_NOTE,
        ),
        aliases=("high potassium", "hyperkalaemia"),
        explanation_policy=_POLICY,
    ),
    "HYPOCALCEMIA_PATTERN": FindingKnowledge(
        code="HYPOCALCEMIA_PATTERN",
        canonical_name="Low calcium",
        definition=(
            "Total serum calcium below the reference interval. Total calcium "
            "follows albumin and is not the same as the ionised calcium."
        ),
        plain_explanation=(
            "Your total calcium is lower than the normal range. Much of the "
            "calcium in blood is carried on a protein called albumin, so when "
            "albumin is low the total calcium reads low even though the "
            "calcium the body actually uses is normal. A doctor should review "
            "this result."
        ),
        common_associations=(
            "a low albumin, which lowers the total without lowering the active "
            "calcium", "vitamin D deficiency", "kidney conditions",
            "parathyroid conditions", "some medicines",
        ),
        must_not_say=(
            "Do not tell the patient to take calcium or vitamin D. A low total "
            "calcium is very often explained entirely by a low albumin and "
            "needs no treatment at all.",
            "Do not name a parathyroid or bone condition.",
        ),
        cautionary_notes=(
            "This system does not correct calcium for albumin, and a corrected "
            "calcium is what a clinician would look at.",
            _SAMPLE_NOTE,
        ),
        aliases=("low calcium", "hypocalcaemia"),
        explanation_policy=_POLICY,
    ),
    "HYPERCALCEMIA_PATTERN": FindingKnowledge(
        code="HYPERCALCEMIA_PATTERN",
        canonical_name="High calcium",
        definition="Total serum calcium above the reference interval.",
        plain_explanation=(
            "Your total calcium is higher than the normal range. This is worth "
            "checking on a repeat sample, because a tight tourniquet during "
            "the blood draw can raise it. A doctor should review this result."
        ),
        common_associations=(
            "a tight tourniquet or dehydration at the time of the sample",
            "parathyroid conditions", "some medicines and supplements",
            "less commonly, other medical conditions",
        ),
        must_not_say=(
            "Do not name a cancer. A raised calcium has several explanations, "
            "most of them not cancer, and raising it from a routine result is "
            "a serious harm.",
            "Do not name a parathyroid condition.",
            "Do not advise stopping calcium or vitamin D supplements.",
        ),
        cautionary_notes=(_SAMPLE_NOTE,),
        aliases=("high calcium", "hypercalcaemia"),
        explanation_policy=_POLICY,
    ),
    "LOW_BICARBONATE_PATTERN": FindingKnowledge(
        code="LOW_BICARBONATE_PATTERN",
        canonical_name="Low bicarbonate",
        definition="Serum bicarbonate below the reference interval.",
        plain_explanation=(
            "Your bicarbonate is lower than the normal range. Bicarbonate "
            "helps keep the blood's acid balance steady. A mildly low value on "
            "a routine sample is often caused by the sample sitting before it "
            "was tested. A doctor should review this result."
        ),
        common_associations=(
            "a sample left standing before testing", "kidney conditions",
            "poorly controlled diabetes", "diarrhoea", "some medicines",
            "breathing faster than usual, including from anxiety",
        ),
        must_not_say=(
            "Do not use the word acidosis, and do not say the blood is acidic. "
            "That is a clinical assessment needing a blood gas, not a routine "
            "panel.",
            "Do not name diabetes or a kidney condition.",
        ),
        cautionary_notes=(
            "Bicarbonate falls in a sample left standing, so a mildly low "
            "value on a routine panel is often an artefact.",
            _SAMPLE_NOTE,
        ),
        aliases=("low bicarbonate", "low co2"),
        explanation_policy=_POLICY,
    ),
}
