"""Map a printed test label to a canonical analyte name, or return nothing.

The alias table is the schema aliases plus the common spellings a lab report
uses. A label that is not in the table resolves to ``None`` - the value is
still carried through the pipeline, marked as an unrecognised analyte, rather
than being force-fitted to the nearest canonical name.
"""
from __future__ import annotations

import re

from intelligence.document.schemas.registry import get_schema, known_schema_types

# Extra spellings beyond what the schemas carry, so free-standing extraction
# (not schema-driven) still canonicalises the common analytes.
_EXTRA_ALIASES: dict[str, str] = {
    "haemoglobin": "hemoglobin", "hb": "hemoglobin", "hgb": "hemoglobin",
    "total leucocyte count": "wbc", "total leukocyte count": "wbc",
    "tlc": "wbc", "white blood cell count": "wbc", "white cell count": "wbc",
    "leucocyte count": "wbc", "wbc count": "wbc",
    "platelet count": "platelets", "plt": "platelets",
    "mean corpuscular volume": "mcv", "mean cell volume": "mcv",
    "serum ferritin": "ferritin", "ferritin level": "ferritin",
    "eosinophil": "eosinophils", "eosinophil count": "eosinophils",
    "absolute eosinophil count": "eosinophils", "aec": "eosinophils",

    "total cholesterol": "cholesterol", "cholesterol total": "cholesterol",
    "serum cholesterol": "cholesterol",
    "hdl cholesterol": "hdl", "hdl-c": "hdl", "hdl - c": "hdl",
    "ldl cholesterol": "ldl", "ldl-c": "ldl", "ldl - c": "ldl",
    "triglyceride": "triglycerides", "tg": "triglycerides", "trig": "triglycerides",
    "fasting blood sugar": "glucose", "fasting glucose": "glucose",
    "fasting plasma glucose": "glucose", "blood sugar fasting": "glucose",
    "plasma glucose": "glucose", "blood glucose": "glucose", "fbs": "glucose",
    "glycated hemoglobin": "hba1c", "glycated haemoglobin": "hba1c",
    "glycosylated hemoglobin": "hba1c", "hba1c (glycated hemoglobin)": "hba1c",
    "a1c": "hba1c",
}

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def _key(label: str) -> str:
    lowered = (label or "").lower().strip()
    lowered = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", lowered).strip()


def _build_table() -> dict[str, str]:
    table: dict[str, str] = {_key(alias): name for alias, name in _EXTRA_ALIASES.items()}
    for report_type in known_schema_types():
        schema = get_schema(report_type)
        if schema is None:
            continue
        for spec in schema.fields:
            table[_key(spec.name)] = spec.name
            for alias in spec.aliases:
                table[_key(alias)] = spec.name
    # A canonical name must also resolve to itself: "MCV" on a report is not an
    # alias of anything, it IS the analyte, and it appears in no schema.
    for name in set(table.values()):
        table.setdefault(_key(name), name)
    return table


_TABLE = _build_table()

#: The canonical names this module will ever emit.
CANONICAL_ANALYTES = frozenset(_TABLE.values())


def canonical_analyte(label: str) -> str | None:
    return _TABLE.get(_key(label))
