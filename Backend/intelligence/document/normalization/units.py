"""Deterministic unit normalisation for the analytes in scope.

The rule table mirrors ``apps.common.units`` on purpose: a value normalised
here and one normalised there must agree, so when the Django pipeline
eventually consumes this module's output over HTTP the numbers line up. The
factors are copied, not imported, because this package does not import Django.

Every conversion is ``normalized = value * factor + offset`` from a versioned
table. A pair the table does not cover is left raw and flagged - never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Bump whenever a factor changes. Callers persist this next to the value.
RULESET_VERSION = "document-units-2024.2"

CANONICAL_UNIT: dict[str, str] = {
    # --- glycaemia. Three separate analytes on purpose: a fasting and a
    # random sample are read against different numbers, and calling them both
    # "glucose" is how a post-meal 7.5 mmol/L becomes a "high" result.
    "glucose": "mmol/L",
    "fasting_glucose": "mmol/L",
    "random_glucose": "mmol/L",
    "hba1c": "mmol/mol",

    # --- lipids -----------------------------------------------------
    "cholesterol": "mmol/L",
    "hdl": "mmol/L",
    "ldl": "mmol/L",
    "triglycerides": "mmol/L",

    # --- full blood count -------------------------------------------
    "hemoglobin": "g/L",
    "hematocrit": "%",
    "rbc": "10^12/L",
    "mcv": "fL",
    "mch": "pg",
    "mchc": "g/L",
    "rdw": "%",
    "wbc": "10^9/L",
    "platelets": "10^9/L",
    # The differential is carried as a PERCENTAGE of white cells. See the note
    # on the rule table below for why an absolute count is left unconverted.
    "neutrophils": "%",
    "lymphocytes": "%",
    "monocytes": "%",
    "eosinophils": "%",
    "basophils": "%",
    "ferritin": "ng/mL",

    # --- renal ------------------------------------------------------
    "creatinine": "umol/L",
    "egfr": "mL/min/1.73m2",
    # Urea weighs the whole molecule; blood urea nitrogen weighs only the
    # nitrogen in it. The same number in mg/dL is therefore a different amount
    # of urea depending on which the report meant, by a factor of about 2.14,
    # so the label - not the unit - has to pick the conversion. Both land in
    # mmol/L of urea and share a reference interval once there.
    "urea": "mmol/L",
    "bun": "mmol/L",
    "urine_albumin_creatinine_ratio": "mg/g",

    # --- liver ------------------------------------------------------
    "alt": "U/L",
    "ast": "U/L",
    "alp": "U/L",
    "ggt": "U/L",
    "bilirubin_total": "umol/L",
    "bilirubin_direct": "umol/L",
    "albumin": "g/L",
    "total_protein": "g/L",

    # --- thyroid ----------------------------------------------------
    "tsh": "mIU/L",
    "free_t4": "pmol/L",
    "free_t3": "pmol/L",

    # --- electrolytes -----------------------------------------------
    "sodium": "mmol/L",
    "potassium": "mmol/L",
    "chloride": "mmol/L",
    "bicarbonate": "mmol/L",
    "calcium": "mmol/L",
}

# (analyte, normalised from-unit) -> (factor, offset), converting into the
# analyte's canonical unit. Kept numerically identical to apps.common.units.
_RULES: dict[tuple[str, str], tuple[float, float]] = {
    ("glucose", "mg/dl"): (0.0555, 0.0),
    ("glucose", "mmol/l"): (1.0, 0.0),
    ("cholesterol", "mg/dl"): (0.02586, 0.0),
    ("cholesterol", "mmol/l"): (1.0, 0.0),
    ("hdl", "mg/dl"): (0.02586, 0.0),
    ("hdl", "mmol/l"): (1.0, 0.0),
    ("ldl", "mg/dl"): (0.02586, 0.0),
    ("ldl", "mmol/l"): (1.0, 0.0),
    ("triglycerides", "mg/dl"): (0.01129, 0.0),
    ("triglycerides", "mmol/l"): (1.0, 0.0),
    ("hemoglobin", "g/dl"): (10.0, 0.0),
    ("hemoglobin", "g/l"): (1.0, 0.0),
    ("hba1c", "%"): (10.929, -23.49735),
    ("hba1c", "mmol/mol"): (1.0, 0.0),
    ("wbc", "10^9/l"): (1.0, 0.0),
    ("wbc", "10^3/ul"): (1.0, 0.0),
    ("wbc", "/ul"): (0.001, 0.0),
    ("platelets", "10^9/l"): (1.0, 0.0),
    ("platelets", "10^3/ul"): (1.0, 0.0),
    ("platelets", "/ul"): (0.001, 0.0),
    ("fasting_glucose", "mg/dl"): (0.0555, 0.0),
    ("fasting_glucose", "mmol/l"): (1.0, 0.0),
    ("random_glucose", "mg/dl"): (0.0555, 0.0),
    ("random_glucose", "mmol/l"): (1.0, 0.0),

    # --- full blood count -------------------------------------------
    ("hematocrit", "%"): (1.0, 0.0),
    ("hematocrit", "l/l"): (100.0, 0.0),
    ("rbc", "10^12/l"): (1.0, 0.0),
    ("rbc", "10^6/ul"): (1.0, 0.0),
    ("mcv", "fl"): (1.0, 0.0),
    ("mch", "pg"): (1.0, 0.0),
    ("mchc", "g/dl"): (10.0, 0.0),
    ("mchc", "g/l"): (1.0, 0.0),
    # RDW-CV, a percentage. RDW-SD is reported in fL and is a different
    # quantity, so it has no rule and is left uncompared rather than checked
    # against the CV interval.
    ("rdw", "%"): (1.0, 0.0),
    # The differential is a PERCENTAGE only. There is deliberately no rule for
    # an absolute count for any of these, so an absolute value is left
    # unconvertible and never gets compared against a percentage reference
    # range. An absolute count and a percentage answer different questions and
    # a report that gives only one cannot be turned into the other.
    ("neutrophils", "%"): (1.0, 0.0),
    ("lymphocytes", "%"): (1.0, 0.0),
    ("monocytes", "%"): (1.0, 0.0),
    ("eosinophils", "%"): (1.0, 0.0),
    ("basophils", "%"): (1.0, 0.0),
    # ng/mL and ug/L are the same number for ferritin.
    ("ferritin", "ng/ml"): (1.0, 0.0),

    # --- renal ------------------------------------------------------
    ("creatinine", "mg/dl"): (88.42, 0.0),
    ("creatinine", "umol/l"): (1.0, 0.0),
    ("egfr", "ml/min/1.73m2"): (1.0, 0.0),
    ("urea", "mg/dl"): (0.1665, 0.0),
    ("urea", "mmol/l"): (1.0, 0.0),
    ("bun", "mg/dl"): (0.357, 0.0),
    ("bun", "mmol/l"): (1.0, 0.0),
    ("urine_albumin_creatinine_ratio", "mg/g"): (1.0, 0.0),
    ("urine_albumin_creatinine_ratio", "mg/mmol"): (8.84, 0.0),

    # --- liver ------------------------------------------------------
    ("alt", "u/l"): (1.0, 0.0),
    ("ast", "u/l"): (1.0, 0.0),
    ("alp", "u/l"): (1.0, 0.0),
    ("ggt", "u/l"): (1.0, 0.0),
    ("bilirubin_total", "mg/dl"): (17.104, 0.0),
    ("bilirubin_total", "umol/l"): (1.0, 0.0),
    ("bilirubin_direct", "mg/dl"): (17.104, 0.0),
    ("bilirubin_direct", "umol/l"): (1.0, 0.0),
    ("albumin", "g/dl"): (10.0, 0.0),
    ("albumin", "g/l"): (1.0, 0.0),
    ("total_protein", "g/dl"): (10.0, 0.0),
    ("total_protein", "g/l"): (1.0, 0.0),

    # --- thyroid ----------------------------------------------------
    # mIU/L and uIU/mL are the same number.
    ("tsh", "miu/l"): (1.0, 0.0),
    ("free_t4", "pmol/l"): (1.0, 0.0),
    ("free_t4", "ng/dl"): (12.87, 0.0),
    ("free_t3", "pmol/l"): (1.0, 0.0),
    ("free_t3", "pg/ml"): (1.536, 0.0),

    # --- electrolytes -----------------------------------------------
    # mEq/L equals mmol/L for the monovalent ions but NOT for calcium, which
    # is divalent. The rules are keyed per analyte so the two cannot be
    # confused; a global "mEq/L means mmol/L" alias would halve or double
    # every calcium result depending on which way it was applied.
    ("sodium", "mmol/l"): (1.0, 0.0),
    ("sodium", "meq/l"): (1.0, 0.0),
    ("potassium", "mmol/l"): (1.0, 0.0),
    ("potassium", "meq/l"): (1.0, 0.0),
    ("chloride", "mmol/l"): (1.0, 0.0),
    ("chloride", "meq/l"): (1.0, 0.0),
    ("bicarbonate", "mmol/l"): (1.0, 0.0),
    ("bicarbonate", "meq/l"): (1.0, 0.0),
    ("calcium", "mmol/l"): (1.0, 0.0),
    ("calcium", "mg/dl"): (0.2495, 0.0),
    ("calcium", "meq/l"): (0.5, 0.0),
}

_UNIT_ALIASES = {
    "mg/dl": "mg/dl", "mg/dL": "mg/dl", "milligram/decilitre": "mg/dl",
    "mmol/l": "mmol/l", "mmol/L": "mmol/l",
    "g/dl": "g/dl", "g/dL": "g/dl", "gm/dl": "g/dl",
    "g/l": "g/l", "g/L": "g/l",
    "%": "%",
    "mmol/mol": "mmol/mol",
    "10^9/l": "10^9/l", "10^9/L": "10^9/l", "x10^9/l": "10^9/l",
    "10*9/l": "10^9/l", "10e9/l": "10^9/l", "10^3/ul": "10^3/ul",
    "x10^3/ul": "10^3/ul", "10*3/ul": "10^3/ul", "k/ul": "10^3/ul",
    "/ul": "/ul", "/µl": "/ul", "/μl": "/ul", "cells/ul": "/ul",
    "fl": "fl", "fL": "fl", "femtolitre": "fl",
    "ng/ml": "ng/ml", "ng/mL": "ng/ml", "ug/l": "ng/ml",
    "µg/l": "ng/ml", "μg/l": "ng/ml",

    # --- counts and indices -----------------------------------------
    "l/l": "l/l",
    "10^12/l": "10^12/l", "x10^12/l": "10^12/l", "10*12/l": "10^12/l",
    "10e12/l": "10^12/l",
    "10^6/ul": "10^6/ul", "x10^6/ul": "10^6/ul", "10*6/ul": "10^6/ul",
    "mill/ul": "10^6/ul", "million/ul": "10^6/ul", "m/ul": "10^6/ul",
    "pg": "pg", "picogram": "pg",

    # --- enzymes and chemistry --------------------------------------
    "u/l": "u/l", "iu/l": "u/l", "units/l": "u/l",
    "umol/l": "umol/l", "µmol/l": "umol/l", "μmol/l": "umol/l",
    "meq/l": "meq/l", "mequiv/l": "meq/l",

    # --- thyroid ----------------------------------------------------
    "miu/l": "miu/l", "uiu/ml": "miu/l", "µiu/ml": "miu/l", "μiu/ml": "miu/l",
    "miu/ml": "miu/l", "mciu/ml": "miu/l",
    "pmol/l": "pmol/l",
    "ng/dl": "ng/dl", "pg/ml": "pg/ml",

    # --- renal ------------------------------------------------------
    "ml/min/1.73m2": "ml/min/1.73m2", "ml/min/1.73 m2": "ml/min/1.73m2",
    "ml/min/1.73m^2": "ml/min/1.73m2", "ml/min/1.73m²": "ml/min/1.73m2",
    # A bare "mL/min" is a creatinine clearance, not a body-surface-normalised
    # eGFR. It is deliberately absent so the two are never treated as one.
    "mg/g": "mg/g", "ug/mg": "mg/g", "µg/mg": "mg/g", "mg/gcreat": "mg/g",
    "mg/mmol": "mg/mmol",
}


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    value: float | None
    unit: str
    original_value: float | None
    original_unit: str
    rule_version: str
    convertible: bool
    detail: str = ""


def normalize_unit_token(unit: str) -> str | None:
    token = (unit or "").strip()
    if token in _UNIT_ALIASES:
        return _UNIT_ALIASES[token]
    lowered = token.lower()
    return _UNIT_ALIASES.get(lowered)


def normalize_value(
    analyte: str, value: float | None, unit: str
) -> NormalizedValue:
    key = (analyte or "").strip().lower()
    canonical = CANONICAL_UNIT.get(key, "")

    if value is None:
        return NormalizedValue(
            value=None, unit=unit, original_value=None, original_unit=unit,
            rule_version=RULESET_VERSION, convertible=False,
            detail="value is not numeric",
        )

    if key not in CANONICAL_UNIT:
        # An analyte this table does not model. Not an error - there is simply
        # nothing to normalise. Whether it should have been extracted at all is
        # the validation stage's call, against the report's schema.
        return NormalizedValue(
            value=value, unit=unit, original_value=value, original_unit=unit,
            rule_version=RULESET_VERSION, convertible=False, detail="",
        )

    token = normalize_unit_token(unit)
    if token is None:
        return NormalizedValue(
            value=value, unit=unit, original_value=value, original_unit=unit,
            rule_version=RULESET_VERSION, convertible=False,
            detail=f"unit {unit!r} not recognised",
        )

    rule = _RULES.get((key, token))
    if rule is None:
        return NormalizedValue(
            value=value, unit=token, original_value=value, original_unit=unit,
            rule_version=RULESET_VERSION, convertible=False,
            detail=f"no conversion rule for {analyte} in {token}",
        )

    factor, offset = rule
    return NormalizedValue(
        value=round(value * factor + offset, 6), unit=canonical or token,
        original_value=value, original_unit=unit,
        rule_version=RULESET_VERSION, convertible=True,
    )
