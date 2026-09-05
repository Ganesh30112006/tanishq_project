from __future__ import annotations

from decimal import Decimal

# Clinical shorthand that must not be title-cased into a different term.
_ACRONYMS = {
    "cvd", "bmi", "bp", "hdl", "ldl", "wbc", "rbc", "cbc", "hba1c", "a1c",
    "spo2", "egfr", "ckd", "copd",
}


def display_term(value: str | None) -> str:
    """Title-case a code for display while preserving clinical acronyms."""
    if not value:
        return ""
    words = str(value).replace("_", " ").split()
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w.capitalize() for w in words)


def display_number(value: object) -> str:
    """Render a numeric clinical value without trailing zero padding.

    ``Decimal("142.0000")`` is stored at column precision, not measured
    precision; printing it raw overstates how precisely it was observed.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        normalized = Decimal(str(value)).normalize()
        if normalized == normalized.to_integral_value():
            normalized = normalized.quantize(Decimal(1))
        return format(normalized, "f")
    return str(value)
