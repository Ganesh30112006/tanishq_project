"""Approved knowledge for the liver patterns.

Each enzyme is its own finding rather than one "abnormal LFT" pattern,
because which enzymes are raised together is the whole of the clinical
information. ALT and AST rising together points somewhere different from ALP
and GGT rising together, and a system that collapsed them into a single
"deranged liver function" would have thrown away the only thing the panel
actually says. Combining them is a level-3 question and is not answered here.

None of these findings names a liver disease. Two of the commonest causes of a
mildly raised ALT in this population - fatty liver and a viral hepatitis
carrier state - cannot be told apart on a liver panel, and the difference
matters enormously to the patient.
"""
from __future__ import annotations

from intelligence.knowledge.findings.model import FindingKnowledge

_ENZYME_POLICY = (
    "Describe which enzyme is raised and by how much relative to the range. "
    "Do not name a liver disease, do not suggest a cause, and do not comment "
    "on alcohol. Always say that a doctor must interpret the panel as a whole."
)

KNOWLEDGE: dict[str, FindingKnowledge] = {
    "ALT_ELEVATION_PATTERN": FindingKnowledge(
        code="ALT_ELEVATION_PATTERN",
        canonical_name="Raised ALT (SGPT)",
        definition="Alanine aminotransferase above the reference interval.",
        plain_explanation=(
            "Your ALT, also printed as SGPT, is higher than the normal range. "
            "ALT is an enzyme found mostly in liver cells, and it goes up when "
            "those cells are irritated. Many everyday things raise it a "
            "little. A doctor should look at it together with the other liver "
            "results."
        ),
        common_associations=(
            "fatty liver", "some medicines, including common pain-killers and "
            "some traditional remedies", "viral hepatitis", "alcohol",
            "recent strenuous exercise", "coeliac and thyroid conditions",
        ),
        must_not_say=(
            "Do not name a liver disease. Fatty liver and viral hepatitis look "
            "the same on this panel and are managed completely differently.",
            "Do not suggest the patient drinks too much. Most raised ALT "
            "results in this population are not alcohol-related, and saying so "
            "is both wrong and hurtful.",
            "Do not advise stopping any medicine.",
        ),
        cautionary_notes=(
            "A mildly raised ALT is common and often settles on a repeat test.",
            "A normal ALT does not exclude liver disease, including cirrhosis.",
        ),
        aliases=("high alt", "raised sgpt"),
        explanation_policy=_ENZYME_POLICY,
        next_steps=("Show this report to your doctor.",),
    ),
    "AST_ELEVATION_PATTERN": FindingKnowledge(
        code="AST_ELEVATION_PATTERN",
        canonical_name="Raised AST (SGOT)",
        definition="Aspartate aminotransferase above the reference interval.",
        plain_explanation=(
            "Your AST, also printed as SGOT, is higher than the normal range. "
            "AST is an enzyme found in the liver but also in muscle and heart, "
            "so a raised value is not always about the liver. A doctor should "
            "review it with the rest of the panel."
        ),
        common_associations=(
            "the same liver causes as a raised ALT", "muscle injury or hard "
            "exercise", "some medicines", "a haemolysed blood sample",
        ),
        must_not_say=(
            "Do not name a liver disease.",
            "Do not assume the liver is the source. AST also comes from "
            "muscle, and a person who exercised hard before the test can have "
            "a raised AST with a completely normal liver.",
            "Do not suggest the patient drinks too much.",
        ),
        aliases=("high ast", "raised sgot"),
        explanation_policy=_ENZYME_POLICY,
    ),
    "ALP_ELEVATION_PATTERN": FindingKnowledge(
        code="ALP_ELEVATION_PATTERN",
        canonical_name="Raised alkaline phosphatase",
        definition="Alkaline phosphatase above the reference interval.",
        plain_explanation=(
            "Your alkaline phosphatase is higher than the normal range. This "
            "enzyme comes from the liver and the bile ducts, and also from "
            "bone, so a raised value does not always point at the liver. A "
            "doctor should review it."
        ),
        common_associations=(
            "conditions affecting the bile ducts", "bone growth in "
            "adolescence", "pregnancy", "bone conditions including vitamin D "
            "deficiency", "some medicines",
        ),
        must_not_say=(
            "Do not say the bile ducts are blocked.",
            "Do not name a bone disease or a cancer. Alkaline phosphatase is "
            "raised in many harmless situations, including normal pregnancy "
            "and normal adolescence.",
        ),
        cautionary_notes=(
            "Whether a raised alkaline phosphatase came from liver or bone "
            "usually needs another test, most often GGT, to separate.",
        ),
        aliases=("high alp", "raised alkaline phosphatase"),
        explanation_policy=_ENZYME_POLICY,
    ),
    "GGT_ELEVATION_PATTERN": FindingKnowledge(
        code="GGT_ELEVATION_PATTERN",
        canonical_name="Raised GGT",
        definition="Gamma-glutamyl transferase above the reference interval.",
        plain_explanation=(
            "Your GGT is higher than the normal range. GGT is an enzyme from "
            "the liver and bile ducts. It is a sensitive test, which means it "
            "goes up easily and often for reasons that turn out not to be "
            "important. A doctor should review it."
        ),
        common_associations=(
            "fatty liver", "alcohol", "many common medicines",
            "conditions affecting the bile ducts", "obesity and diabetes",
        ),
        must_not_say=(
            "Do not use this result to say anything about how much the patient "
            "drinks. GGT is raised by many medicines and by fatty liver, and "
            "treating it as an alcohol test is a well-known mistake that "
            "damages trust and gets the diagnosis wrong.",
            "Do not name a liver disease.",
        ),
        cautionary_notes=(
            "GGT is sensitive but not specific: a raised value narrows very "
            "little on its own.",
        ),
        aliases=("high ggt", "raised gamma gt"),
        explanation_policy=_ENZYME_POLICY,
    ),
    "BILIRUBIN_ELEVATION_PATTERN": FindingKnowledge(
        code="BILIRUBIN_ELEVATION_PATTERN",
        canonical_name="Raised bilirubin",
        definition="Total bilirubin above the reference interval.",
        plain_explanation=(
            "Your bilirubin is higher than the normal range. Bilirubin is a "
            "yellow substance made when old red blood cells are broken down, "
            "and the liver clears it. A mildly raised value is common and is "
            "often a harmless inherited variation. A doctor should review it."
        ),
        common_associations=(
            "Gilbert's syndrome, a common and harmless inherited variation",
            "fasting or a recent illness", "liver conditions",
            "conditions affecting the bile ducts",
            "increased breakdown of red blood cells",
        ),
        must_not_say=(
            "Do not say the patient has jaundice or liver disease. Gilbert's "
            "syndrome affects roughly one person in twenty, needs no "
            "treatment, and produces exactly this result.",
            "Do not say the bile ducts are blocked.",
        ),
        cautionary_notes=(
            "Separating the conjugated (direct) from the unconjugated fraction "
            "is what distinguishes the harmless causes from the ones that "
            "matter, and a report giving only a total cannot do that.",
        ),
        aliases=("high bilirubin", "raised total bilirubin"),
        explanation_policy=_ENZYME_POLICY,
    ),
    "LOW_ALBUMIN_PATTERN": FindingKnowledge(
        code="LOW_ALBUMIN_PATTERN",
        canonical_name="Low albumin",
        definition="Serum albumin below the reference interval.",
        plain_explanation=(
            "Your albumin is lower than the normal range. Albumin is the main "
            "protein in blood and it is made by the liver. It falls during any "
            "illness or inflammation, and also in some liver, kidney and "
            "nutritional conditions. A doctor should review it."
        ),
        common_associations=(
            "any acute illness or inflammation", "poor nutrition",
            "liver conditions", "protein loss through the kidneys or the gut",
            "pregnancy",
        ),
        must_not_say=(
            "Do not say the patient is malnourished. Albumin falls in "
            "inflammation regardless of what the person eats, and calling a "
            "sick patient malnourished on this basis is a common error.",
            "Do not name a liver or kidney disease.",
            "Do not recommend protein supplements.",
        ),
        cautionary_notes=(
            "A low albumin lowers the total calcium without changing the "
            "ionised calcium that matters, so a calcium on the same panel may "
            "read low for this reason alone.",
        ),
        aliases=("hypoalbuminaemia", "low serum albumin"),
    ),
}
