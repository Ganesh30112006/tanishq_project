"""Approved knowledge for the metabolic patterns.

See the package docstring for what each field is for and why
``must_not_say`` is the part that does real work.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "HYPERGLYCEMIA_PATTERN": FindingKnowledge(
        code="HYPERGLYCEMIA_PATTERN",
        canonical_name="High blood glucose",
        definition="Blood glucose above the reference interval on this report.",
        plain_explanation=(
            "Your blood glucose is higher than the normal range. Whether this "
            "matters depends on whether the sample was taken fasting, and on "
            "other tests. A doctor should review it."
        ),
        common_associations=(
            "diabetes", "prediabetes", "a non-fasting sample",
            "acute illness or stress", "steroid medicines",
        ),
        must_not_say=(
            "Do not say the patient has diabetes. Diagnosis needs a confirmed, "
            "correctly-timed sample and a clinician's judgement.",
            "Do not suggest any change to medicine or diet.",
        ),
        cautionary_notes=(
            "This system cannot tell a fasting sample from a random one unless "
            "the report says so, and the two are read against different ranges.",
        ),
        aliases=("high blood sugar", "raised glucose"),
    ),
    "ELEVATED_HBA1C_PATTERN": FindingKnowledge(
        code="ELEVATED_HBA1C_PATTERN",
        canonical_name="Raised HbA1c",
        definition=(
            "HbA1c above the guideline threshold for a normal result. This is a "
            "decision threshold, not a population reference interval."
        ),
        plain_explanation=(
            "Your HbA1c is above the level usually considered normal. HbA1c "
            "reflects average blood sugar over the past two to three months. A "
            "doctor should review this result."
        ),
        common_associations=("prediabetes", "diabetes", "conditions affecting red cells"),
        must_not_say=(
            "Do not say the patient has diabetes or prediabetes. Those are "
            "diagnoses a clinician makes.",
        ),
        cautionary_notes=(
            "HbA1c is unreliable in anaemia, recent blood loss or transfusion, "
            "and some haemoglobin variants.",
        ),
        aliases=("raised hba1c", "high a1c"),
    ),
    "DYSLIPIDEMIA_PATTERN": FindingKnowledge(
        code="DYSLIPIDEMIA_PATTERN",
        canonical_name="Lipid results outside the usual targets",
        definition=(
            "One or more of total cholesterol, LDL, HDL or triglycerides sits "
            "outside the commonly used target. These are treatment targets, not "
            "reference intervals."
        ),
        plain_explanation=(
            "One or more of your lipid (fat) results is outside the usual "
            "target. These targets are guides for treatment and depend on your "
            "overall heart risk, so a doctor needs to interpret them for you."
        ),
        common_associations=("diet", "physical activity", "genetics",
                             "thyroid and kidney conditions", "some medicines"),
        must_not_say=(
            "Do not call this abnormal. The numbers are targets, and the right "
            "target differs from person to person.",
            "Do not recommend a statin or any other treatment.",
            "Do not produce a cardiovascular risk estimate here - that is the "
            "governed risk model's job, not a finding's.",
        ),
        aliases=("abnormal lipids", "high cholesterol"),
    ),
}
