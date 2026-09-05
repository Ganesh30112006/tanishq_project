"""Deterministic text extraction for laboratory reports (spec sections 12, 15).

This is a rule-based fallback / first pass. It recognises ``analyte  value  unit``
patterns for known tests and returns per-field confidence. It never guesses: a
line that does not clearly match a known analyte is ignored, and a value that
cannot be parsed as a number is returned as text with a low confidence and an
``AMBIGUOUS`` state.

The intelligence service's NLP endpoint may supplement this, but any value it
proposes still passes through deterministic validation before it is trusted
(spec section 12 - "Do not allow an LLM to directly write trusted medical
values to the database without validation").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Canonical analyte -> accepted aliases (lower-case, no punctuation).
ANALYTE_ALIASES: dict[str, tuple[str, ...]] = {
    "glucose": ("glucose", "fasting glucose", "fasting blood glucose", "fbs", "blood sugar"),
    "hba1c": ("hba1c", "hemoglobin a1c", "haemoglobin a1c", "glycated hemoglobin", "a1c"),
    "cholesterol": ("total cholesterol", "cholesterol total", "cholesterol"),
    "hdl": ("hdl", "hdl cholesterol", "hdl c"),
    "ldl": ("ldl", "ldl cholesterol", "ldl c"),
    "triglycerides": ("triglycerides", "trig", "tg"),
    "creatinine": ("creatinine", "serum creatinine"),
    "hemoglobin": ("hemoglobin", "haemoglobin", "hb", "hgb"),
    "wbc": ("wbc", "white blood cells", "white blood cell count", "leukocytes"),
    "platelets": ("platelets", "platelet count", "plt"),
}

# Units we understand for each analyte (used only to tag; conversion is done by
# apps.common.units).
KNOWN_UNITS = {
    "mg/dl", "mg/dL", "mmol/l", "mmol/L", "mmol/mol", "%", "g/dl", "g/dL", "g/l",
    "umol/l", "µmol/l", "10^9/l", "x10^9/l", "/ul", "cells/ul",
}

_VALUE_UNIT_RE = re.compile(
    r"""(?P<value>-?\d+(?:\.\d+)?)      # number
        \s*
        (?P<unit>%|[A-Za-zµ]+/?[A-Za-z0-9^]*|10\^\d+/[A-Za-z]+)?  # optional unit token
    """,
    re.VERBOSE,
)


@dataclass(slots=True)
class ExtractedValue:
    analyte: str
    raw_line: str
    value_text: str
    value_number: Decimal | None
    unit: str
    entity_confidence: float
    context_confidence: float

    @property
    def parsed(self) -> bool:
        return self.value_number is not None


@dataclass(slots=True)
class ExtractionOutput:
    values: list[ExtractedValue] = field(default_factory=list)
    unmatched_lines: list[str] = field(default_factory=list)

    def by_analyte(self) -> dict[str, list[ExtractedValue]]:
        out: dict[str, list[ExtractedValue]] = {}
        for v in self.values:
            out.setdefault(v.analyte, []).append(v)
        return out


def _normalize_label(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _match_analyte(label: str) -> tuple[str | None, float]:
    """Match a row label to a canonical analyte.

    Exact (normalized) equality wins. Otherwise a prefix match is allowed
    ("glucose fasting", "glucose random"), preferring the most specific
    (longest) alias. Loose substring matching is deliberately avoided so that
    e.g. "HDL Cholesterol" is not captured as "cholesterol".
    """
    norm = _normalize_label(label)
    for analyte, aliases in ANALYTE_ALIASES.items():
        if norm in aliases:
            return analyte, 0.99

    best: tuple[str, float, int] | None = None
    for analyte, aliases in ANALYTE_ALIASES.items():
        for alias in aliases:
            if norm.startswith(alias + " ") and (best is None or len(alias) > best[2]):
                best = (analyte, 0.85, len(alias))
    if best is not None:
        return best[0], best[1]
    return None, 0.0


def extract_text(text: str) -> ExtractionOutput:
    """Extract analyte values from already-OCR'd report text."""
    out = ExtractionOutput()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Split "label : value unit" or "label   value unit".
        parts = re.split(r"[:\t]|\s{2,}", line, maxsplit=1)
        if len(parts) != 2:
            m = re.match(r"(?P<label>[A-Za-z][A-Za-z0-9 /()\-]+?)\s+(?P<rest>-?\d.*)$", line)
            if not m:
                out.unmatched_lines.append(line)
                continue
            label, rest = m.group("label"), m.group("rest")
        else:
            label, rest = parts[0], parts[1]

        analyte, ctx_conf = _match_analyte(label)
        if analyte is None:
            out.unmatched_lines.append(line)
            continue

        vm = _VALUE_UNIT_RE.search(rest)
        if not vm:
            out.values.append(
                ExtractedValue(analyte, line, rest.strip(), None, "", 0.3, ctx_conf)
            )
            continue

        value_text = vm.group("value")
        unit = (vm.group("unit") or "").strip()
        try:
            number = Decimal(value_text)
            entity_conf = 0.95 if unit else 0.8
        except InvalidOperation:
            number = None
            entity_conf = 0.3
        if unit and unit not in KNOWN_UNITS:
            # Unit token present but unrecognised - keep it, lower confidence.
            entity_conf = min(entity_conf, 0.6)

        out.values.append(
            ExtractedValue(analyte, line, value_text, number, unit, entity_conf, ctx_conf)
        )
    return out
