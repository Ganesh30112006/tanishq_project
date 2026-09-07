"""Approved knowledge for the thyroid patterns.

TSH and the free hormones are separate findings because the pattern between
them is the diagnosis, and the pattern is a level-3 question. A raised TSH
with a normal free T4 and a raised TSH with a low free T4 are different
situations with different management, and neither of them is named here.

The standing caution across all four: thyroid tests are unreliable during and
shortly after any acute illness, and the pregnancy intervals are different in
every trimester. A report cannot tell whether either applies.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

_POLICY = (
    "Describe which thyroid measurement is outside its range. Do not name "
    "hypothyroidism, hyperthyroidism, or any thyroid disease, and do not "
    "combine TSH with the free hormones into a pattern - that is a "
    "conclusion this level may not reach. Always say a doctor must interpret "
    "the panel together, usually on a repeat sample."
)
_ILLNESS_NOTE = (
    "Thyroid results are unreliable during and shortly after any acute "
    "illness, and shift in every trimester of pregnancy. Neither is visible "
    "from the report."
)

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "TSH_ELEVATION_PATTERN": FindingKnowledge(
        code="TSH_ELEVATION_PATTERN",
        canonical_name="Raised TSH",
        definition="Thyroid stimulating hormone above the reference interval.",
        plain_explanation=(
            "Your TSH is higher than the normal range. TSH is the signal the "
            "brain sends to the thyroid gland, and it rises when the gland is "
            "working harder than usual to keep up. This often needs a repeat "
            "test before anything can be said, because TSH moves with illness "
            "and even with the time of day. A doctor should review it."
        ),
        common_associations=(
            "an underactive thyroid gland", "recovery from a recent illness",
            "some medicines", "an inherited variation in the thyroid gland",
            "iodine intake",
        ),
        must_not_say=(
            "Do not say the patient has hypothyroidism or an underactive "
            "thyroid. That needs the free T4, a repeat sample, and a "
            "clinician's judgement.",
            "Do not recommend thyroxine or any other treatment.",
            "Do not combine this with a free T4 result to name a condition.",
        ),
        cautionary_notes=(
            _ILLNESS_NOTE,
            "TSH varies through the day and is highest at night, so the time "
            "of the sample affects the number.",
        ),
        aliases=("high tsh", "raised thyroid stimulating hormone"),
        explanation_policy=_POLICY,
        next_steps=("Show this report to your doctor.",),
    ),
    "TSH_SUPPRESSION_PATTERN": FindingKnowledge(
        code="TSH_SUPPRESSION_PATTERN",
        canonical_name="Low TSH",
        definition="Thyroid stimulating hormone below the reference interval.",
        plain_explanation=(
            "Your TSH is lower than the normal range. TSH is the signal the "
            "brain sends to the thyroid gland, and it falls when there is "
            "already plenty of thyroid hormone in the blood. It also falls in "
            "early pregnancy and during illness. A doctor should review it."
        ),
        common_associations=(
            "an overactive thyroid gland", "taking thyroid hormone tablets",
            "the first three months of pregnancy", "acute illness",
            "steroid medicines",
        ),
        must_not_say=(
            "Do not say the patient has hyperthyroidism or an overactive "
            "thyroid.",
            "Do not suggest changing the dose of any thyroid medicine. A low "
            "TSH in someone already taking thyroxine is a dose question for "
            "their doctor, not a new diagnosis.",
            "Do not combine this with a free T4 result to name a condition.",
        ),
        cautionary_notes=(_ILLNESS_NOTE,),
        aliases=("low tsh", "suppressed tsh"),
        explanation_policy=_POLICY,
    ),
    "LOW_FREE_T4_PATTERN": FindingKnowledge(
        code="LOW_FREE_T4_PATTERN",
        canonical_name="Low free T4",
        definition="Free thyroxine below the reference interval.",
        plain_explanation=(
            "Your free T4 is lower than the normal range. Free T4 is the main "
            "thyroid hormone circulating in the blood. This result has to be "
            "read together with your TSH, and a doctor should do that."
        ),
        common_associations=(
            "an underactive thyroid gland", "serious illness of any kind",
            "some medicines", "conditions affecting the pituitary gland",
        ),
        must_not_say=(
            "Do not name a thyroid condition.",
            "Do not recommend thyroxine.",
        ),
        cautionary_notes=(
            _ILLNESS_NOTE,
            "Free T4 assays differ enough between laboratories that the "
            "laboratory's own interval should be used whenever it is printed.",
        ),
        aliases=("low ft4", "low free thyroxine"),
        explanation_policy=_POLICY,
    ),
    "HIGH_FREE_T4_PATTERN": FindingKnowledge(
        code="HIGH_FREE_T4_PATTERN",
        canonical_name="High free T4",
        definition="Free thyroxine above the reference interval.",
        plain_explanation=(
            "Your free T4 is higher than the normal range. Free T4 is the main "
            "thyroid hormone circulating in the blood. This result has to be "
            "read together with your TSH, and a doctor should do that."
        ),
        common_associations=(
            "an overactive thyroid gland", "taking thyroid hormone tablets, "
            "especially if the sample was taken soon after a dose",
            "inflammation of the thyroid gland",
        ),
        must_not_say=(
            "Do not name a thyroid condition.",
            "Do not suggest changing the dose of any thyroid medicine.",
        ),
        cautionary_notes=(
            _ILLNESS_NOTE,
            "In a person taking thyroxine, a sample drawn within a few hours "
            "of the tablet reads high without meaning anything.",
        ),
        aliases=("high ft4", "raised free thyroxine"),
        explanation_policy=_POLICY,
    ),
}
