"""Built-in report schemas.

Only the types with a deterministic, well-agreed field list are defined here
for now: the blood panels the cardiovascular missing-data workflow actually
asks for. Narrative types (radiology, pathology, discharge summaries) have no
fixed field list and are handled as free text by later stages, so they are
deliberately absent rather than given an empty schema that would always read
COMPLETE.

Plausibility bounds mirror ``apps.reports.default_schemas`` in canonical units.
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


_SCHEMAS: dict[ReportType, ReportSchema] = {
    ReportType.GLUCOSE: ReportSchema(
        report_type=ReportType.GLUCOSE, version=1,
        expected_sections=("CHEMISTRY",),
        fields=(
            _mgdl_mmol("glucose", required=True,
                      aliases=("fasting glucose", "fbs", "blood sugar",
                               "plasma glucose", "random blood sugar"),
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
        report_type=ReportType.CBC, version=1,
        expected_sections=("COMPLETE BLOOD COUNT", "HEMOGRAM"),
        fields=(
            ReportFieldSpec(
                name="hemoglobin", required=True,
                aliases=("hb", "hgb", "haemoglobin"),
                accepted_units=("g/dL", "g/L"), canonical_unit="g/L",
                min_value=20.0, max_value=250.0,
            ),
            ReportFieldSpec(
                name="wbc", required=True,
                aliases=("white blood cells", "total leucocyte count", "tlc"),
                accepted_units=("10^9/L", "/uL", "x10^3/uL"),
                canonical_unit="10^9/L", min_value=0.1, max_value=500.0,
            ),
            ReportFieldSpec(
                name="platelets", required=True,
                aliases=("plt", "platelet count"),
                accepted_units=("10^9/L", "/uL", "x10^3/uL"),
                canonical_unit="10^9/L", min_value=1.0, max_value=3000.0,
            ),
        ),
    ),
}


def get_schema(report_type: ReportType) -> ReportSchema | None:
    return _SCHEMAS.get(report_type)


def known_schema_types() -> list[ReportType]:
    return sorted(_SCHEMAS, key=lambda rt: rt.value)
