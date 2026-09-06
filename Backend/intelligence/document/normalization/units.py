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
RULESET_VERSION = "document-units-2024.1"

CANONICAL_UNIT: dict[str, str] = {
    "glucose": "mmol/L",
    "cholesterol": "mmol/L",
    "hdl": "mmol/L",
    "ldl": "mmol/L",
    "triglycerides": "mmol/L",
    "hemoglobin": "g/L",
    "hba1c": "mmol/mol",
    "wbc": "10^9/L",
    "platelets": "10^9/L",
    "mcv": "fL",
    "ferritin": "ng/mL",
    "eosinophils": "%",
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
    ("mcv", "fl"): (1.0, 0.0),
    # ng/mL and ug/L are the same number for ferritin.
    ("ferritin", "ng/ml"): (1.0, 0.0),
    # An eosinophil PERCENTAGE only. There is deliberately no rule for an
    # absolute count, so an absolute value is left unconvertible and never
    # gets compared against a percentage reference range.
    ("eosinophils", "%"): (1.0, 0.0),
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
