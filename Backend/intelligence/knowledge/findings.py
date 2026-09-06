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


_KNOWLEDGE: dict[str, FindingKnowledge] = {
    "ANEMIA_PATTERN": FindingKnowledge(
        code="ANEMIA_PATTERN",
        canonical_name="Low haemoglobin (anaemia pattern)",
        definition=(
            "Haemoglobin below the reference interval for the patient's age and "
            "sex on this report."
        ),
        plain_explanation=(
            "Your haemoglobin is lower than the normal range printed on this "
            "report. Haemoglobin carries oxygen in the blood. A low value has "
            "many possible causes and needs a doctor to look at it along with "
            "your history and other tests."
        ),
        common_associations=(
            "iron deficiency", "blood loss", "vitamin B12 or folate deficiency",
            "chronic disease", "kidney disease", "thalassaemia and other "
            "inherited conditions",
        ),
        must_not_say=(
            "Do not name a cause. A low haemoglobin on its own does not "
            "identify which of the many causes applies.",
            "Do not suggest iron tablets or any other treatment.",
        ),
        cautionary_notes=(
            "A single low result can be a sampling or dilution artefact; it is "
            "usually confirmed on a repeat sample.",
        ),
        aliases=("low haemoglobin", "low hemoglobin", "anaemia"),
        references=("WHO haemoglobin thresholds for anaemia",),
        next_steps=("Show this report to your doctor.",),
    ),
    "POLYCYTHEMIA_PATTERN": FindingKnowledge(
        code="POLYCYTHEMIA_PATTERN",
        canonical_name="High haemoglobin",
        definition="Haemoglobin above the reference interval on this report.",
        plain_explanation=(
            "Your haemoglobin is higher than the normal range printed on this "
            "report. This can happen for simple reasons such as dehydration, "
            "and it can also have other causes. A doctor should review it."
        ),
        common_associations=(
            "dehydration", "smoking", "living at high altitude",
            "chronic low blood oxygen", "bone-marrow conditions",
        ),
        must_not_say=("Do not name a bone-marrow disease from this value alone.",),
        aliases=("high haemoglobin", "raised hemoglobin"),
    ),
    "LEUKOCYTOSIS_PATTERN": FindingKnowledge(
        code="LEUKOCYTOSIS_PATTERN",
        canonical_name="High white blood cell count",
        definition="Total white cell count above the reference interval.",
        plain_explanation=(
            "Your white blood cell count is higher than the normal range. "
            "White cells fight infection, and the count also rises with stress, "
            "some medicines and other conditions. A doctor should review this "
            "along with how you are feeling."
        ),
        common_associations=(
            "infection", "inflammation", "physical stress",
            "corticosteroid medicines", "smoking", "blood disorders",
        ),
        must_not_say=(
            "Do not say an infection has been detected. A raised white count is "
            "not a diagnosis of infection.",
            "Do not suggest antibiotics.",
        ),
        aliases=("high wbc", "raised white cell count"),
    ),
    "LEUKOPENIA_PATTERN": FindingKnowledge(
        code="LEUKOPENIA_PATTERN",
        canonical_name="Low white blood cell count",
        definition="Total white cell count below the reference interval.",
        plain_explanation=(
            "Your white blood cell count is lower than the normal range. This "
            "has several possible causes, including recent viral illness and "
            "some medicines. A doctor should review it."
        ),
        common_associations=(
            "recent viral infection", "some medicines", "nutritional deficiency",
            "bone-marrow conditions", "autoimmune conditions",
        ),
        must_not_say=("Do not suggest the immune system has failed.",),
        aliases=("low wbc",),
    ),
    "THROMBOCYTOPENIA_PATTERN": FindingKnowledge(
        code="THROMBOCYTOPENIA_PATTERN",
        canonical_name="Low platelet count",
        definition="Platelet count below the reference interval.",
        plain_explanation=(
            "Your platelet count is lower than the normal range. Platelets help "
            "blood to clot. A doctor should review this result, especially if "
            "you bruise or bleed easily."
        ),
        common_associations=(
            "viral infection", "some medicines", "liver disease",
            "immune conditions", "clumping in the sample tube (a false low)",
        ),
        must_not_say=("Do not tell the patient they are at risk of bleeding.",),
        cautionary_notes=(
            "Platelet clumping in the sample tube is a common cause of a "
            "falsely low count and is usually excluded on a blood film.",
        ),
        aliases=("low platelets",),
    ),
    "THROMBOCYTOSIS_PATTERN": FindingKnowledge(
        code="THROMBOCYTOSIS_PATTERN",
        canonical_name="High platelet count",
        definition="Platelet count above the reference interval.",
        plain_explanation=(
            "Your platelet count is higher than the normal range. This is often "
            "a temporary response to infection, inflammation or iron "
            "deficiency. A doctor should review it."
        ),
        common_associations=(
            "infection or inflammation", "iron deficiency", "after surgery",
            "bone-marrow conditions",
        ),
        must_not_say=("Do not name a bone-marrow disease from this value alone.",),
        aliases=("high platelets",),
    ),
    "EOSINOPHILIA_PATTERN": FindingKnowledge(
        code="EOSINOPHILIA_PATTERN",
        canonical_name="Raised eosinophil count",
        definition="Eosinophil count or percentage above the reference interval.",
        plain_explanation=(
            "Your eosinophil count is above the normal range printed on this "
            "report. Eosinophils are a type of white blood cell. A raised count "
            "can occur in several settings, including allergy, a reaction to a "
            "medicine, and some infections. This result on its own does not "
            "identify a cause, and a doctor should interpret it."
        ),
        common_associations=(
            "allergic conditions including asthma and eczema",
            "reaction to a medicine", "parasitic infection",
            "some skin conditions", "less commonly, blood disorders",
        ),
        must_not_say=(
            "Do not tell a patient they have a parasitic infection. It is one of "
            "several possibilities and cannot be established from a blood count.",
            "Do not name a blood cancer.",
            "Do not advise stopping any medicine.",
        ),
        aliases=("high eosinophils", "eosinophil elevation"),
    ),
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
    "MICROCYTOSIS_PATTERN": FindingKnowledge(
        code="MICROCYTOSIS_PATTERN",
        canonical_name="Small red blood cells (low MCV)",
        definition="Mean corpuscular volume below the reference interval.",
        plain_explanation=(
            "Your red blood cells are smaller than usual. This is a clue that "
            "helps a doctor work out the cause of a low haemoglobin."
        ),
        common_associations=("iron deficiency", "thalassaemia trait",
                             "chronic disease"),
        must_not_say=("Do not name a cause from the cell size alone.",),
        aliases=("low mcv",),
    ),
    "MACROCYTOSIS_PATTERN": FindingKnowledge(
        code="MACROCYTOSIS_PATTERN",
        canonical_name="Large red blood cells (high MCV)",
        definition="Mean corpuscular volume above the reference interval.",
        plain_explanation=(
            "Your red blood cells are larger than usual. This is a clue that "
            "helps a doctor work out the cause of a low haemoglobin."
        ),
        common_associations=("vitamin B12 or folate deficiency", "alcohol use",
                             "thyroid conditions", "some medicines"),
        must_not_say=("Do not name a cause from the cell size alone.",),
        aliases=("high mcv",),
    ),
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


def get(code: str) -> FindingKnowledge | None:
    return _KNOWLEDGE.get(code)


def known_codes() -> list[str]:
    return sorted(_KNOWLEDGE)
