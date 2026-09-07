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
    "POSSIBLE_CHRONIC_KIDNEY_DISEASE": FindingKnowledge(
        code="POSSIBLE_CHRONIC_KIDNEY_DISEASE",
        canonical_name="Pattern that may suggest chronic kidney disease",
        definition=(
            "A reduced eGFR or albumin in the urine, shown to have been "
            "present for more than three months. The three months is part of "
            "the definition, not a precaution."
        ),
        plain_explanation=(
            "Your kidney results have stayed outside the usual range over "
            "more than three months. That length of time is what separates a "
            "lasting change from a temporary one. This is a pattern for your "
            "doctor to look into, not a diagnosis, and there is a lot that "
            "can be done when it is found early."
        ),
        common_associations=(
            "diabetes", "high blood pressure", "some long-term medicines",
            "inherited kidney conditions",
            "the gradual fall in kidney function that comes with age",
        ),
        must_not_say=(
            "Do not give a CKD stage. Staging needs both an eGFR and an "
            "albumin-to-creatinine ratio and is a clinical act.",
            "Do not say the kidneys are failing, and do not mention dialysis "
            "or transplant. Most people found at this stage never need "
            "either, and raising it is frightening and misleading.",
            "Do not recommend any medicine, diet or fluid restriction.",
            "Do not say this is permanent or irreversible.",
        ),
        cautionary_notes=(
            "Acute kidney injury on top of an existing problem produces the "
            "same picture and cannot be excluded from laboratory reports.",
            "eGFR equations differ between laboratories, so two reports are "
            "not always directly comparable.",
        ),
        aliases=("possible ckd", "chronic kidney disease pattern"),
        references=("KDIGO 2012 CKD evaluation and management guideline",),
        next_steps=("Show these reports to your doctor.",),
    ),
    "POSSIBLE_PRIMARY_HYPOTHYROIDISM": FindingKnowledge(
        code="POSSIBLE_PRIMARY_HYPOTHYROIDISM",
        canonical_name="Pattern that may suggest an underactive thyroid gland",
        definition=(
            "A raised TSH together with a free T4 below its reference "
            "interval - the biochemical picture of overt primary "
            "hypothyroidism, on a single sample."
        ),
        plain_explanation=(
            "Your thyroid results show a pattern that can occur when the "
            "thyroid gland is underactive. This needs to be checked on a "
            "second sample before anything is decided, because illness and "
            "some medicines produce the same pattern. A doctor should review "
            "it."
        ),
        common_associations=(
            "an underactive thyroid gland", "recovery from a recent illness",
            "some medicines", "an autoimmune thyroid condition",
        ),
        must_not_say=(
            "Do not say the patient has hypothyroidism. This is one sample, "
            "and confirmation on a repeat is required.",
            "Do not recommend thyroxine or any other treatment, and do not "
            "suggest a dose.",
            "Do not tell the patient this explains their tiredness, weight or "
            "mood. Those connections are common, frequently wrong, and "
            "distressing when they turn out not to hold.",
        ),
        cautionary_notes=(
            "Thyroid results are unreliable during and shortly after any "
            "acute illness, and the pregnancy intervals differ in every "
            "trimester. The report shows neither.",
        ),
        aliases=("possible hypothyroidism", "underactive thyroid pattern"),
    ),
    "POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM": FindingKnowledge(
        code="POSSIBLE_SUBCLINICAL_HYPOTHYROIDISM",
        canonical_name="Pattern that may suggest a mildly underactive thyroid",
        definition=(
            "A raised TSH with a free T4 that is inside its reference "
            "interval. The normal free T4 is what makes the pattern "
            "subclinical rather than overt."
        ),
        plain_explanation=(
            "Your TSH is raised but your thyroid hormone level is still "
            "within the normal range. This is a mild pattern. It often "
            "returns to normal by itself, and a repeat test after a few weeks "
            "is the usual next step. A doctor should review it."
        ),
        common_associations=(
            "a mild change in the thyroid gland that often settles",
            "recovery from a recent illness",
            "an autoimmune thyroid condition", "some medicines",
        ),
        must_not_say=(
            "Do not say the patient has a thyroid condition. A large share of "
            "these results are normal on a repeat sample.",
            "Do not recommend thyroxine. Whether mild results should be "
            "treated at all is genuinely debated, and it depends on the "
            "person's age, symptoms and other results.",
            "Do not describe this as an early stage of anything.",
        ),
        cautionary_notes=(
            "Thyroid results are unreliable during and shortly after any "
            "acute illness, and the pregnancy intervals differ in every "
            "trimester. The report shows neither.",
        ),
        aliases=("possible subclinical hypothyroidism",),
    ),
    "PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY": FindingKnowledge(
        code="PATTERN_SUGGESTIVE_OF_HEPATOCELLULAR_INJURY",
        canonical_name="Liver panel shaped towards the liver cells",
        definition=(
            "ALT raised out of proportion to alkaline phosphatase, with an R "
            "ratio above 5. A description of the shape of the panel, not of a "
            "cause."
        ),
        plain_explanation=(
            "The pattern of your liver results points towards the liver cells "
            "rather than the bile ducts. This tells a doctor which further "
            "tests are useful. It does not say what the cause is, and there "
            "are several common causes that look identical here."
        ),
        common_associations=(
            "fatty liver", "viral hepatitis", "some medicines and remedies",
            "alcohol", "less commonly, autoimmune and inherited conditions",
        ),
        must_not_say=(
            "Do not name a liver disease. Fatty liver and chronic viral "
            "hepatitis produce this same shape and are managed completely "
            "differently.",
            "Do not comment on alcohol intake.",
            "Do not say the liver is damaged or inflamed.",
            "Do not advise stopping any medicine.",
        ),
        cautionary_notes=(
            "AST also comes from muscle, so hard exercise before the test "
            "shifts the ratio with a normal liver.",
        ),
        aliases=("hepatocellular pattern",),
    ),
    "PATTERN_SUGGESTIVE_OF_CHOLESTASIS": FindingKnowledge(
        code="PATTERN_SUGGESTIVE_OF_CHOLESTASIS",
        canonical_name="Liver panel shaped towards the bile ducts",
        definition=(
            "Alkaline phosphatase raised out of proportion to ALT, with an R "
            "ratio below 2. A description of the shape of the panel, not of a "
            "cause."
        ),
        plain_explanation=(
            "The pattern of your liver results points towards the bile ducts "
            "rather than the liver cells. This tells a doctor which further "
            "tests are useful. It does not say what the cause is."
        ),
        common_associations=(
            "conditions affecting the bile ducts", "some medicines",
            "bone conditions, which raise the same enzyme without any liver "
            "problem", "normal pregnancy and normal adolescence",
        ),
        must_not_say=(
            "Do not say the bile ducts are blocked, and do not mention "
            "gallstones or a tumour.",
            "Do not name a liver disease.",
            "Do not assume the liver is the source at all. Alkaline "
            "phosphatase also comes from bone, and without a raised GGT a "
            "bone source is at least as likely.",
        ),
        cautionary_notes=(
            "A GGT is what separates a liver source from a bone source. "
            "Without it this shape is much weaker than it looks.",
        ),
        aliases=("cholestatic pattern",),
    ),
}
