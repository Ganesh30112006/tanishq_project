"""Built-in report schemas.

A schema says what a report of a given type is expected to contain, what the
fields are called on real reports, which units are accepted, and the *wide*
plausibility bounds outside which a number is a read error rather than a sick
patient. It does not say what is normal - that is the reference-range table,
and it is a different question with different consequences.

Narrative types (radiology, pathology, discharge summaries) have no fixed
field list and are handled as free text by later stages, so they are
deliberately absent rather than given an empty schema that would always read
COMPLETE.

**Required vs optional.** Only the fields a report of this type is not really a
report of this type without are ``required``; everything else is optional but
still recognised, normalised and validated. A CBC that omits the differential
is still a complete CBC, and marking every field required would turn ordinary
reports into INCOMPLETE ones and bury the cases that genuinely are.

Plausibility bounds mirror ``apps.reports.default_schemas`` in canonical units
where the two overlap.
"""
from __future__ import annotations

from intelligence.document.contracts import ReportType
from intelligence.document.schemas.model import ReportFieldSpec, ReportSchema


def _mgdl_mmol(name: str, *, required: bool, aliases: tuple[str, ...],
               lo: float, hi: float) -> ReportFieldSpec:
    return ReportFieldSpec(
        name=name, required=required, aliases=aliases,
        accepted_units=("mg/dL", "mmol/L"), canonical_unit="mmol/L",
        min_value=lo, max_value=hi,
    )


def _percent(name: str, *, aliases: tuple[str, ...] = ()) -> ReportFieldSpec:
    """A differential-count percentage. Never an absolute count - see units."""
    return ReportFieldSpec(
        name=name, required=False, aliases=aliases,
        accepted_units=("%",), canonical_unit="%",
        min_value=0.0, max_value=100.0,
    )


def _enzyme(name: str, *, aliases: tuple[str, ...]) -> ReportFieldSpec:
    return ReportFieldSpec(
        name=name, required=False, aliases=aliases,
        accepted_units=("U/L", "IU/L"), canonical_unit="U/L",
        min_value=0.0, max_value=20000.0,
    )


def _ion(name: str, *, aliases: tuple[str, ...], lo: float, hi: float,
         required: bool = False) -> ReportFieldSpec:
    return ReportFieldSpec(
        name=name, required=required, aliases=aliases,
        accepted_units=("mmol/L", "mEq/L"), canonical_unit="mmol/L",
        min_value=lo, max_value=hi,
    )


_SCHEMAS: dict[ReportType, ReportSchema] = {
    ReportType.GLUCOSE: ReportSchema(
        report_type=ReportType.GLUCOSE, version=2,
        expected_sections=("CHEMISTRY",),
        required_any=(("fasting_glucose", "random_glucose", "glucose"),),
        notes=(
            "A fasting and a random sample are different analytes here. A "
            "report that does not say which was taken resolves to the "
            "unqualified 'glucose', which has no fallback interval."
        ),
        fields=(
            _mgdl_mmol("glucose", required=False,
                       aliases=("blood sugar", "plasma glucose",
                                "blood glucose", "serum glucose"),
                       lo=1.0, hi=60.0),
            _mgdl_mmol("fasting_glucose", required=False,
                       aliases=("fasting glucose", "fasting blood sugar",
                                "fbs", "fasting plasma glucose"),
                       lo=1.0, hi=60.0),
            _mgdl_mmol("random_glucose", required=False,
                       aliases=("random blood sugar", "rbs", "ppbs",
                                "post prandial blood sugar"),
                       lo=1.0, hi=60.0),
        ),
    ),
    ReportType.HBA1C: ReportSchema(
        report_type=ReportType.HBA1C, version=1,
        expected_sections=("CHEMISTRY",),
        fields=(
            ReportFieldSpec(
                name="hba1c", required=True,
                aliases=("a1c", "glycated hemoglobin", "glycated haemoglobin",
                         "glycosylated hemoglobin"),
                accepted_units=("%", "mmol/mol"), canonical_unit="mmol/mol",
                min_value=20.0, max_value=195.0,
            ),
        ),
    ),
    ReportType.LIPID_PROFILE: ReportSchema(
        report_type=ReportType.LIPID_PROFILE, version=1,
        expected_sections=("LIPID PANEL", "LIPID PROFILE"),
        fields=(
            _mgdl_mmol("cholesterol", required=True,
                      aliases=("total cholesterol",), lo=1.0, hi=20.0),
            _mgdl_mmol("hdl", required=True,
                      aliases=("hdl cholesterol",), lo=0.1, hi=5.0),
            _mgdl_mmol("ldl", required=True,
                      aliases=("ldl cholesterol",), lo=0.1, hi=15.0),
            _mgdl_mmol("triglycerides", required=True,
                      aliases=("tg", "triglyceride"), lo=0.1, hi=30.0),
        ),
    ),
    ReportType.CBC: ReportSchema(
        report_type=ReportType.CBC, version=2,
        expected_sections=("COMPLETE BLOOD COUNT", "HEMOGRAM"),
        notes=(
            "The differential is carried as a percentage. An absolute count "
            "has no conversion rule on purpose, so it is held for review "
            "rather than compared against a percentage interval."
        ),
        fields=(
            ReportFieldSpec(
                name="hemoglobin", required=True,
                aliases=("hb", "hgb", "haemoglobin"),
                accepted_units=("g/dL", "g/L"), canonical_unit="g/L",
                min_value=20.0, max_value=250.0,
            ),
            ReportFieldSpec(
                name="hematocrit", required=False,
                aliases=("hct", "pcv", "packed cell volume", "haematocrit"),
                accepted_units=("%", "L/L"), canonical_unit="%",
                min_value=5.0, max_value=75.0,
            ),
            ReportFieldSpec(
                name="rbc", required=False,
                aliases=("red blood cell count", "rbc count", "red cell count"),
                accepted_units=("10^12/L", "10^6/uL"), canonical_unit="10^12/L",
                min_value=0.5, max_value=10.0,
            ),
            ReportFieldSpec(
                name="mcv", required=False,
                aliases=("mean corpuscular volume", "mean cell volume"),
                accepted_units=("fL",), canonical_unit="fL",
                min_value=40.0, max_value=160.0,
            ),
            ReportFieldSpec(
                name="mch", required=False,
                aliases=("mean corpuscular hemoglobin",
                         "mean corpuscular haemoglobin"),
                accepted_units=("pg",), canonical_unit="pg",
                min_value=10.0, max_value=60.0,
            ),
            ReportFieldSpec(
                name="mchc", required=False,
                aliases=("mean corpuscular hemoglobin concentration",),
                accepted_units=("g/dL", "g/L"), canonical_unit="g/L",
                min_value=200.0, max_value=450.0,
            ),
            ReportFieldSpec(
                name="rdw", required=False,
                aliases=("red cell distribution width", "rdw-cv"),
                accepted_units=("%",), canonical_unit="%",
                min_value=5.0, max_value=40.0,
            ),
            ReportFieldSpec(
                name="wbc", required=True,
                aliases=("white blood cells", "total leucocyte count", "tlc"),
                accepted_units=("10^9/L", "/uL", "x10^3/uL"),
                canonical_unit="10^9/L", min_value=0.1, max_value=500.0,
            ),
            _percent("neutrophils", aliases=("polymorphs", "neutrophil")),
            _percent("lymphocytes", aliases=("lymphocyte",)),
            _percent("monocytes", aliases=("monocyte",)),
            _percent("eosinophils", aliases=("eosinophil",)),
            _percent("basophils", aliases=("basophil",)),
            ReportFieldSpec(
                name="platelets", required=True,
                aliases=("plt", "platelet count"),
                accepted_units=("10^9/L", "/uL", "x10^3/uL"),
                canonical_unit="10^9/L", min_value=1.0, max_value=3000.0,
            ),
        ),
    ),
    ReportType.KIDNEY_FUNCTION: ReportSchema(
        report_type=ReportType.KIDNEY_FUNCTION, version=1,
        expected_sections=("RENAL FUNCTION TEST", "KIDNEY FUNCTION TEST",
                           "RENAL PANEL"),
        notes=(
            "Urea and blood urea nitrogen are separate fields. They differ by "
            "a factor of about 2.14 and merging them is a silent error on "
            "every report that prints one but not the other."
        ),
        fields=(
            ReportFieldSpec(
                name="creatinine", required=True,
                aliases=("serum creatinine", "s. creatinine"),
                accepted_units=("mg/dL", "umol/L"), canonical_unit="umol/L",
                min_value=8.0, max_value=2000.0,
            ),
            ReportFieldSpec(
                name="egfr", required=False,
                aliases=("estimated gfr", "estimated glomerular filtration rate"),
                accepted_units=("mL/min/1.73m2",),
                canonical_unit="mL/min/1.73m2",
                min_value=1.0, max_value=200.0,
            ),
            ReportFieldSpec(
                name="urea", required=False,
                aliases=("blood urea", "serum urea"),
                accepted_units=("mg/dL", "mmol/L"), canonical_unit="mmol/L",
                min_value=0.3, max_value=100.0,
            ),
            ReportFieldSpec(
                name="bun", required=False,
                aliases=("blood urea nitrogen", "urea nitrogen"),
                accepted_units=("mg/dL", "mmol/L"), canonical_unit="mmol/L",
                min_value=0.3, max_value=100.0,
            ),
        ),
    ),
    ReportType.URINALYSIS: ReportSchema(
        report_type=ReportType.URINALYSIS, version=1,
        expected_sections=("URINE ROUTINE", "URINALYSIS"),
        notes=(
            "Only the quantitative albumin-to-creatinine ratio is modelled. A "
            "dipstick protein result is a qualitative grade (trace, 1+, 2+), "
            "which the numeric extractor does not read and which is not "
            "turned into a number here."
        ),
        fields=(
            ReportFieldSpec(
                name="urine_albumin_creatinine_ratio", required=False,
                aliases=("albumin creatinine ratio", "acr", "uacr",
                         "urine albumin creatinine ratio"),
                accepted_units=("mg/g", "mg/mmol"), canonical_unit="mg/g",
                min_value=0.0, max_value=30000.0,
            ),
        ),
    ),
    ReportType.LIVER_FUNCTION: ReportSchema(
        report_type=ReportType.LIVER_FUNCTION, version=1,
        expected_sections=("LIVER FUNCTION TEST", "HEPATIC PANEL", "LFT"),
        fields=(
            _enzyme("alt", aliases=("sgpt", "alanine aminotransferase")),
            _enzyme("ast", aliases=("sgot", "aspartate aminotransferase")),
            _enzyme("alp", aliases=("alkaline phosphatase",)),
            _enzyme("ggt", aliases=("gamma glutamyl transferase", "ggtp")),
            ReportFieldSpec(
                name="bilirubin_total", required=False,
                aliases=("total bilirubin", "bilirubin"),
                accepted_units=("mg/dL", "umol/L"), canonical_unit="umol/L",
                min_value=0.0, max_value=1000.0,
            ),
            ReportFieldSpec(
                name="bilirubin_direct", required=False,
                aliases=("direct bilirubin", "conjugated bilirubin"),
                accepted_units=("mg/dL", "umol/L"), canonical_unit="umol/L",
                min_value=0.0, max_value=800.0,
            ),
            ReportFieldSpec(
                name="albumin", required=False,
                aliases=("serum albumin",),
                accepted_units=("g/dL", "g/L"), canonical_unit="g/L",
                min_value=5.0, max_value=70.0,
            ),
            ReportFieldSpec(
                name="total_protein", required=False,
                aliases=("total protein", "serum total protein"),
                accepted_units=("g/dL", "g/L"), canonical_unit="g/L",
                min_value=20.0, max_value=140.0,
            ),
        ),
    ),
    ReportType.THYROID: ReportSchema(
        report_type=ReportType.THYROID, version=1,
        expected_sections=("THYROID PROFILE", "THYROID FUNCTION TEST"),
        notes=(
            "Free T4 and free T3 only. Total T3/T4 move with binding proteins "
            "- in pregnancy, on the oral contraceptive pill - and are not "
            "interchangeable with the free hormones, so they are not aliased "
            "onto these fields."
        ),
        fields=(
            ReportFieldSpec(
                name="tsh", required=True,
                aliases=("thyroid stimulating hormone", "s. tsh"),
                accepted_units=("mIU/L", "uIU/mL"), canonical_unit="mIU/L",
                min_value=0.001, max_value=500.0,
            ),
            ReportFieldSpec(
                name="free_t4", required=False,
                aliases=("ft4", "free thyroxine"),
                accepted_units=("pmol/L", "ng/dL"), canonical_unit="pmol/L",
                min_value=0.5, max_value=200.0,
            ),
            ReportFieldSpec(
                name="free_t3", required=False,
                aliases=("ft3", "free triiodothyronine"),
                accepted_units=("pmol/L", "pg/mL"), canonical_unit="pmol/L",
                min_value=0.3, max_value=60.0,
            ),
        ),
    ),
    ReportType.ELECTROLYTES: ReportSchema(
        report_type=ReportType.ELECTROLYTES, version=1,
        expected_sections=("SERUM ELECTROLYTES", "ELECTROLYTES"),
        notes=(
            "Calcium here is TOTAL calcium, which moves with albumin. An "
            "ionised calcium has its own, much narrower interval and is "
            "deliberately not aliased onto this field."
        ),
        fields=(
            _ion("sodium", aliases=("serum sodium", "na"),
                 lo=90.0, hi=200.0, required=True),
            _ion("potassium", aliases=("serum potassium", "k"),
                 lo=1.0, hi=12.0, required=True),
            _ion("chloride", aliases=("serum chloride", "cl"),
                 lo=50.0, hi=160.0),
            _ion("bicarbonate", aliases=("hco3", "co2", "total co2"),
                 lo=2.0, hi=60.0),
            ReportFieldSpec(
                name="calcium", required=False,
                aliases=("serum calcium", "total calcium"),
                accepted_units=("mg/dL", "mmol/L", "mEq/L"),
                canonical_unit="mmol/L",
                min_value=0.8, max_value=5.0,
            ),
        ),
    ),
}


def get_schema(report_type: ReportType) -> ReportSchema | None:
    return _SCHEMAS.get(report_type)


def known_schema_types() -> list[ReportType]:
    return sorted(_SCHEMAS, key=lambda rt: rt.value)
