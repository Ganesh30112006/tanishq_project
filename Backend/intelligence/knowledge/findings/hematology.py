"""Approved knowledge for the haematology patterns.

See the package docstring for what each field is for and why
``must_not_say`` is the part that does real work.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

KNOWLEDGE: dict[str, FindingKnowledge] = {
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
    "RDW_ELEVATION_PATTERN": FindingKnowledge(
        code="RDW_ELEVATION_PATTERN",
        canonical_name="Red cells of uneven size (high RDW)",
        definition=(
            "Red cell distribution width, as a coefficient of variation, above "
            "the reference interval. It measures how much the red cells vary "
            "in size, not whether they are large or small."
        ),
        plain_explanation=(
            "Your red blood cells vary more than usual in size. On its own "
            "this says nothing about how you are. It is a clue a doctor uses "
            "alongside the haemoglobin and the cell size to work out the cause "
            "of a low haemoglobin."
        ),
        common_associations=(
            "iron deficiency, often before the haemoglobin falls",
            "vitamin B12 or folate deficiency",
            "a recent transfusion or recent treatment",
            "two causes of anaemia present at once",
        ),
        must_not_say=(
            "Do not name a cause. A raised RDW narrows nothing by itself.",
            "Do not present this as an abnormality the patient should worry "
            "about. It is an index, not a symptom.",
        ),
        cautionary_notes=(
            "RDW-CV, the percentage reported here, and RDW-SD, reported in "
            "femtolitres, are different measurements and are not "
            "interchangeable.",
        ),
        aliases=("high rdw", "anisocytosis"),
    ),
}
