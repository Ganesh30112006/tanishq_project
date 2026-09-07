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
    # --- full blood count -------------------------------------------
    "haemoglobin": "hemoglobin", "hb": "hemoglobin", "hgb": "hemoglobin",
    "haematocrit": "hematocrit", "hct": "hematocrit", "pcv": "hematocrit",
    "packed cell volume": "hematocrit",
    "red blood cell count": "rbc", "red cell count": "rbc",
    "rbc count": "rbc", "erythrocyte count": "rbc", "total rbc": "rbc",
    "total leucocyte count": "wbc", "total leukocyte count": "wbc",
    "tlc": "wbc", "white blood cell count": "wbc", "white cell count": "wbc",
    "leucocyte count": "wbc", "wbc count": "wbc",
    "platelet count": "platelets", "plt": "platelets",
    "mean corpuscular volume": "mcv", "mean cell volume": "mcv",
    "mean corpuscular hemoglobin": "mch",
    "mean corpuscular haemoglobin": "mch", "mean cell hemoglobin": "mch",
    "mean corpuscular hemoglobin concentration": "mchc",
    "mean corpuscular haemoglobin concentration": "mchc",
    "red cell distribution width": "rdw", "rdw-cv": "rdw", "rdw cv": "rdw",
    "serum ferritin": "ferritin", "ferritin level": "ferritin",
    # The differential. Every one of these names the PERCENTAGE; an absolute
    # count carries a unit the rule table refuses to convert, so it is held for
    # review rather than compared against a percentage interval.
    "neutrophil": "neutrophils", "neutrophil count": "neutrophils",
    "polymorphs": "neutrophils", "polymorphonuclear cells": "neutrophils",
    "segmented neutrophils": "neutrophils", "anc": "neutrophils",
    "absolute neutrophil count": "neutrophils",
    "lymphocyte": "lymphocytes", "lymphocyte count": "lymphocytes",
    "absolute lymphocyte count": "lymphocytes",
    "monocyte": "monocytes", "monocyte count": "monocytes",
    "eosinophil": "eosinophils", "eosinophil count": "eosinophils",
    "absolute eosinophil count": "eosinophils", "aec": "eosinophils",
    "basophil": "basophils", "basophil count": "basophils",

    # --- lipids -----------------------------------------------------
    "total cholesterol": "cholesterol", "cholesterol total": "cholesterol",
    "serum cholesterol": "cholesterol",
    "hdl cholesterol": "hdl", "hdl-c": "hdl", "hdl - c": "hdl",
    "ldl cholesterol": "ldl", "ldl-c": "ldl", "ldl - c": "ldl",
    "triglyceride": "triglycerides", "tg": "triglycerides", "trig": "triglycerides",

    # --- glycaemia. Which sample was taken changes the answer, so a label
    # that says "fasting" and one that says "random" resolve to different
    # analytes, and a bare "Glucose" resolves to neither.
    "fasting blood sugar": "fasting_glucose", "fasting glucose": "fasting_glucose",
    "fasting plasma glucose": "fasting_glucose",
    "blood sugar fasting": "fasting_glucose", "fbs": "fasting_glucose",
    "fbg": "fasting_glucose", "glucose fasting": "fasting_glucose",
    "random blood sugar": "random_glucose", "rbs": "random_glucose",
    "random glucose": "random_glucose", "glucose random": "random_glucose",
    "post prandial blood sugar": "random_glucose", "ppbs": "random_glucose",
    "postprandial blood sugar": "random_glucose",
    "post prandial glucose": "random_glucose",
    "plasma glucose": "glucose", "blood glucose": "glucose",
    "serum glucose": "glucose",
    "glycated hemoglobin": "hba1c", "glycated haemoglobin": "hba1c",
    "glycosylated hemoglobin": "hba1c", "hba1c (glycated hemoglobin)": "hba1c",
    "a1c": "hba1c",

    # --- renal ------------------------------------------------------
    "serum creatinine": "creatinine", "s creatinine": "creatinine",
    "creatinine serum": "creatinine", "plasma creatinine": "creatinine",
    "estimated gfr": "egfr", "egfr (ckd-epi)": "egfr",
    "estimated glomerular filtration rate": "egfr", "gfr estimated": "egfr",
    "blood urea": "urea", "serum urea": "urea", "urea serum": "urea",
    "blood urea nitrogen": "bun", "blood urea nitrogen (bun)": "bun",
    "urea nitrogen": "bun",
    "urine albumin creatinine ratio": "urine_albumin_creatinine_ratio",
    "albumin creatinine ratio": "urine_albumin_creatinine_ratio",
    "acr": "urine_albumin_creatinine_ratio",
    "uacr": "urine_albumin_creatinine_ratio",
    "microalbumin creatinine ratio": "urine_albumin_creatinine_ratio",

    # --- liver. Indian reports print SGPT/SGOT far more often than ALT/AST.
    "sgpt": "alt", "sgpt (alt)": "alt", "alt (sgpt)": "alt",
    "alanine aminotransferase": "alt", "alanine transaminase": "alt",
    "sgot": "ast", "sgot (ast)": "ast", "ast (sgot)": "ast",
    "sgot/ast": "ast", "sgpt/alt": "alt",
    "aspartate aminotransferase": "ast", "aspartate transaminase": "ast",
    "alkaline phosphatase": "alp", "serum alkaline phosphatase": "alp",
    "gamma gt": "ggt", "gamma glutamyl transferase": "ggt",
    "gamma-glutamyl transpeptidase": "ggt", "ggtp": "ggt",
    "total bilirubin": "bilirubin_total", "bilirubin total": "bilirubin_total",
    "serum bilirubin total": "bilirubin_total", "bilirubin": "bilirubin_total",
    "direct bilirubin": "bilirubin_direct",
    "bilirubin direct": "bilirubin_direct",
    "conjugated bilirubin": "bilirubin_direct",
    "serum albumin": "albumin", "albumin serum": "albumin",
    "total protein": "total_protein", "serum total protein": "total_protein",
    "total proteins": "total_protein",

    # --- thyroid ----------------------------------------------------
    "thyroid stimulating hormone": "tsh", "tsh ultrasensitive": "tsh",
    "s tsh": "tsh", "tsh (ultrasensitive)": "tsh",
    "free t4": "free_t4", "ft4": "free_t4", "free thyroxine": "free_t4",
    "free t3": "free_t3", "ft3": "free_t3",
    "free triiodothyronine": "free_t3",

    # --- electrolytes -----------------------------------------------
    "serum sodium": "sodium", "na": "sodium", "na+": "sodium",
    "serum potassium": "potassium", "k": "potassium", "k+": "potassium",
    "serum chloride": "chloride", "cl": "chloride", "cl-": "chloride",
    "bicarbonate (hco3)": "bicarbonate", "hco3": "bicarbonate",
    "co2": "bicarbonate", "total co2": "bicarbonate",
    "serum bicarbonate": "bicarbonate",
    "serum calcium": "calcium", "total calcium": "calcium",
    "calcium total": "calcium",
}

#: Labels that must never be resolved by the alias table, because the same
#: printed name means a different quantity from the one we would map it to.
#: Each of these is left unrecognised - held for review - rather than folded
#: into an analyte whose reference range does not apply to it.
_NEVER_RESOLVE: frozenset[str] = frozenset({
    # An ionised (free) calcium has its own, much narrower interval; reading it
    # against the total-calcium interval calls a normal result low.
    "ionised calcium", "ionized calcium", "free calcium", "calcium ionised",
    "calcium ionized",
    # RDW-SD is a width in femtolitres, not the CV percentage.
    "rdw-sd", "rdw sd",
    # A creatinine clearance is not a body-surface-normalised eGFR.
    "creatinine clearance", "ccr", "cockcroft gault",
    # Indirect bilirubin is derived, not measured, and has its own range.
    "indirect bilirubin", "unconjugated bilirubin",
    # Globulin and the A/G ratio are derived from albumin and total protein.
    "globulin", "a g ratio", "albumin globulin ratio",
})

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
_BLOCKED = frozenset(_key(name) for name in _NEVER_RESOLVE)

#: The canonical names this module will ever emit.
CANONICAL_ANALYTES = frozenset(_TABLE.values())


def canonical_analyte(label: str) -> str | None:
    key = _key(label)
    if key in _BLOCKED:
        return None
    return _TABLE.get(key)
