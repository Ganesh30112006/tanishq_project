"""Deterministic unit normalization (spec section 16).

Conversions are pure arithmetic driven by a versioned rule table. An LLM never
performs numeric unit conversion. Callers must persist the returned
``rule_version`` alongside both the original and normalized values.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.common.errors import ValidationFailed

CONVERSION_RULESET_VERSION = "units-2024.1"


@dataclass(frozen=True, slots=True)
class ConversionResult:
    original_value: Decimal
    original_unit: str
    normalized_value: Decimal
    normalized_unit: str
    rule_version: str


# Canonical (normalized) unit per analyte.
_CANONICAL_UNIT: dict[str, str] = {
    "glucose": "mmol/L",
    "cholesterol": "mmol/L",
    "hdl": "mmol/L",
    "ldl": "mmol/L",
    "triglycerides": "mmol/L",
    "hemoglobin": "g/L",
    "hba1c": "mmol/mol",
    "creatinine": "umol/L",
}

# Linear rules: normalized = value * factor + offset, keyed by (analyte, from_unit).
# Each entry converts *into* the analyte's canonical unit.
_LINEAR_RULES: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("glucose", "mg/dl"): (Decimal("0.0555"), Decimal("0")),
    ("glucose", "mmol/l"): (Decimal("1"), Decimal("0")),
    ("cholesterol", "mg/dl"): (Decimal("0.02586"), Decimal("0")),
    ("cholesterol", "mmol/l"): (Decimal("1"), Decimal("0")),
    ("hdl", "mg/dl"): (Decimal("0.02586"), Decimal("0")),
    ("hdl", "mmol/l"): (Decimal("1"), Decimal("0")),
    ("ldl", "mg/dl"): (Decimal("0.02586"), Decimal("0")),
    ("ldl", "mmol/l"): (Decimal("1"), Decimal("0")),
    ("triglycerides", "mg/dl"): (Decimal("0.01129"), Decimal("0")),
    ("triglycerides", "mmol/l"): (Decimal("1"), Decimal("0")),
    ("hemoglobin", "g/dl"): (Decimal("10"), Decimal("0")),
    ("hemoglobin", "g/l"): (Decimal("1"), Decimal("0")),
    ("creatinine", "mg/dl"): (Decimal("88.42"), Decimal("0")),
    ("creatinine", "umol/l"): (Decimal("1"), Decimal("0")),
    # HbA1c: IFCC mmol/mol = (NGSP % - 2.15) * 10.929
    ("hba1c", "%"): (Decimal("10.929"), Decimal("-23.49735")),
    ("hba1c", "mmol/mol"): (Decimal("1"), Decimal("0")),
}

_UNIT_ALIASES = {
    "mg/dl": "mg/dl",
    "mg/dL": "mg/dl",
    "milligram/decilitre": "mg/dl",
    "mmol/l": "mmol/l",
    "mmol/L": "mmol/l",
    "g/dl": "g/dl",
    "g/dL": "g/dl",
    "g/l": "g/l",
    "g/L": "g/l",
    "umol/l": "umol/l",
    "µmol/l": "umol/l",
    "%": "%",
    "mmol/mol": "mmol/mol",
}


def canonical_unit(analyte: str) -> str:
    key = analyte.strip().lower()
    if key not in _CANONICAL_UNIT:
        raise ValidationFailed(f"Unknown analyte '{analyte}'.", details={"analyte": analyte})
    return _CANONICAL_UNIT[key]


def normalize_unit_token(unit: str) -> str:
    token = unit.strip()
    if token in _UNIT_ALIASES:
        return _UNIT_ALIASES[token]
    lowered = token.lower()
    if lowered in _UNIT_ALIASES:
        return _UNIT_ALIASES[lowered]
    raise ValidationFailed(f"Unrecognized unit '{unit}'.", details={"unit": unit})


def convert(value: Decimal | float | int | str, from_unit: str, analyte: str) -> ConversionResult:
    """Convert ``value`` in ``from_unit`` to the canonical unit for ``analyte``."""
    analyte_key = analyte.strip().lower()
    target_unit = canonical_unit(analyte_key)
    from_token = normalize_unit_token(from_unit)

    rule = _LINEAR_RULES.get((analyte_key, from_token))
    if rule is None:
        raise ValidationFailed(
            f"No conversion rule for {analyte} from '{from_unit}'.",
            details={"analyte": analyte, "from_unit": from_unit},
        )

    original = Decimal(str(value))
    factor, offset = rule
    normalized = (original * factor + offset).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return ConversionResult(
        original_value=original,
        original_unit=from_unit.strip(),
        normalized_value=normalized,
        normalized_unit=target_unit,
        rule_version=CONVERSION_RULESET_VERSION,
    )
