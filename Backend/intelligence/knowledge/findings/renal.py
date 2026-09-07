"""Approved knowledge for the renal patterns.

The recurring caution across this whole system is the same one: a kidney
result taken at a single moment describes that moment. Dehydration, a recent
meal, a contrast scan, an anti-inflammatory tablet and an acute illness all
move these numbers, and every one of them recovers. Chronic kidney disease is
defined by an abnormality that persists for at least ninety days, which is a
statement no single report can make - so nothing here may make it.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "CREATININE_ELEVATION_PATTERN": FindingKnowledge(
        code="CREATININE_ELEVATION_PATTERN",
        canonical_name="Raised creatinine",
        definition="Serum creatinine above the reference interval on this report.",
        plain_explanation=(
            "Your creatinine is higher than the normal range printed on this "
            "report. Creatinine is a waste product that the kidneys clear from "
            "the blood, so this can be a sign that the kidneys are not "
            "clearing it as well as usual. It also rises for simpler reasons, "
            "such as not drinking enough water. A doctor should review it."
        ),
        common_associations=(
            "dehydration", "reduced kidney function",
            "some medicines including pain-killers of the ibuprofen type",
            "a recent scan with contrast dye", "a high meat intake",
            "large muscle mass or heavy exercise before the test",
        ),
        must_not_say=(
            "Do not say the patient has kidney disease or kidney failure. A "
            "single raised creatinine cannot tell a temporary change from a "
            "lasting one.",
            "Do not advise stopping any medicine.",
            "Do not tell the patient to restrict protein or fluids.",
        ),
        cautionary_notes=(
            "Creatinine tracks muscle mass, so the same number means different "
            "things in a large young man and a small elderly woman. A value "
            "inside the reference interval does not rule out reduced kidney "
            "function.",
        ),
        aliases=("high creatinine", "raised serum creatinine"),
        next_steps=("Show this report to your doctor.",),
    ),
    "REDUCED_EGFR_PATTERN": FindingKnowledge(
        code="REDUCED_EGFR_PATTERN",
        canonical_name="Reduced estimated GFR",
        definition=(
            "Estimated glomerular filtration rate below 60 mL/min/1.73m2. This "
            "is a staging boundary from a guideline, not a population "
            "reference interval."
        ),
        plain_explanation=(
            "Your estimated kidney filtration rate (eGFR) is below the level "
            "usually taken as normal. eGFR is calculated from your creatinine, "
            "age and sex. One low reading does not mean lasting kidney "
            "disease, because eGFR falls temporarily when you are dehydrated "
            "or unwell. A doctor should review this and may repeat the test."
        ),
        common_associations=(
            "dehydration or acute illness at the time of the test",
            "reduced kidney function", "some medicines",
            "normal ageing, which lowers eGFR gradually",
        ),
        must_not_say=(
            "Do not say the patient has chronic kidney disease, and do not "
            "give a CKD stage. Chronic means the abnormality has lasted at "
            "least ninety days, which one report cannot show.",
            "Do not tell the patient their kidneys are failing.",
            "Do not advise stopping any medicine or changing their diet.",
        ),
        cautionary_notes=(
            "eGFR equations are less accurate at values above 60, in people at "
            "the extremes of body size, in pregnancy, and in people with "
            "unusual muscle mass.",
            "The equation used matters. If the report does not say which, the "
            "number cannot be compared reliably with an older one.",
        ),
        aliases=("low egfr", "reduced gfr"),
        references=("KDIGO 2012 clinical practice guideline for the evaluation "
                    "and management of chronic kidney disease",),
        next_steps=("Show this report to your doctor. A repeat test is often "
                    "needed before anything can be concluded.",),
    ),
    "UREA_ELEVATION_PATTERN": FindingKnowledge(
        code="UREA_ELEVATION_PATTERN",
        canonical_name="Raised blood urea",
        definition=(
            "Blood urea, or blood urea nitrogen, above the reference interval."
        ),
        plain_explanation=(
            "Your blood urea is higher than the normal range. Urea is a waste "
            "product the kidneys remove. It rises when the kidneys are not "
            "clearing it well, and also when a person is dehydrated or has "
            "been eating a lot of protein. A doctor should review it."
        ),
        common_associations=(
            "dehydration", "reduced kidney function", "a high protein intake",
            "bleeding in the stomach or intestine", "some medicines including "
            "steroids",
        ),
        must_not_say=(
            "Do not say the patient has kidney disease. Urea rises for several "
            "reasons that have nothing to do with the kidneys.",
            "Do not tell the patient to reduce their protein intake.",
        ),
        cautionary_notes=(
            "Urea moves with hydration much more than creatinine does, so it "
            "is the less specific of the two.",
        ),
        aliases=("high urea", "raised bun", "azotaemia"),
    ),
    "ALBUMINURIA_PATTERN": FindingKnowledge(
        code="ALBUMINURIA_PATTERN",
        canonical_name="Albumin in the urine",
        definition=(
            "Urine albumin-to-creatinine ratio above 30 mg/g, the KDIGO A1/A2 "
            "boundary. A staging threshold, not a reference interval."
        ),
        plain_explanation=(
            "Your urine sample contains more albumin (a protein) than usual. "
            "Healthy kidneys keep most protein in the blood. This can be a "
            "sign of kidney strain, and it also rises for a few days after "
            "fever, hard exercise or a urine infection. A doctor should review "
            "it, and the test is usually repeated before anything is decided."
        ),
        common_associations=(
            "diabetes affecting the kidneys", "high blood pressure",
            "a urine infection", "fever or hard exercise in the days before "
            "the test", "menstruation at the time of the sample",
        ),
        must_not_say=(
            "Do not say the patient has diabetic kidney disease or any other "
            "named kidney condition.",
            "Do not say the kidneys are damaged. A single raised ratio is not "
            "evidence of lasting damage.",
            "Do not recommend any medicine.",
        ),
        cautionary_notes=(
            "Confirmation on a second or third sample over three to six months "
            "is required before albuminuria is considered persistent.",
        ),
        aliases=("microalbuminuria", "raised acr", "protein in urine"),
        references=("KDIGO albuminuria categories A1-A3",),
    ),
}
