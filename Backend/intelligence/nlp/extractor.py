"""Rule-based clinical entity extraction (spec sections 12, 15).

Recognises ``analyte value unit`` patterns for known tests and returns per-field
confidence, plus negation / uncertainty detection so a phrase like
"no evidence of glucose intolerance" is not mistaken for a measurement.

This is deterministic. A trained medical NER model can replace :func:`extract`
behind the same response contract; downstream, any value it proposes still
passes through deterministic validation in Django before it is trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ANALYTE_ALIASES: dict[str, tuple[str, ...]] = {
    "glucose": ("glucose", "fasting glucose", "fasting blood glucose", "fbs", "blood sugar"),
    "hba1c": ("hba1c", "hemoglobin a1c", "haemoglobin a1c", "glycated hemoglobin", "a1c"),
    "cholesterol": ("total cholesterol", "cholesterol total", "cholesterol"),
    "hdl": ("hdl", "hdl cholesterol"),
    "ldl": ("ldl", "ldl cholesterol"),
    "triglycerides": ("triglycerides", "trig", "tg"),
    "creatinine": ("creatinine", "serum creatinine"),
    "hemoglobin": ("hemoglobin", "haemoglobin", "hb", "hgb"),
    "wbc": ("wbc", "white blood cells", "white blood cell count", "leukocytes"),
    "platelets": ("platelets", "platelet count", "plt"),
}

_NEGATION = ("no ", "not ", "without ", "denies ", "negative for ", "no evidence of ", "ruled out")
_UNCERTAINTY = ("possible", "probable", "likely", "suspected", "cannot exclude", "equivocal", "borderline")

_VALUE_UNIT_RE = re.compile(
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|[A-Za-zµ]+/?[A-Za-z0-9^]*|10\^\d+/[A-Za-z]+)?"
)


@dataclass(slots=True)
class Entity:
    kind: str
    analyte: str
    text: str
    value: float | None
    unit: str
    entity_confidence: float
    context_confidence: float
    negated: bool
    uncertain: bool


@dataclass(slots=True)
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    status: str = "OK"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _match_analyte(label: str) -> tuple[str | None, float]:
    n = _norm(label)
    for analyte, aliases in ANALYTE_ALIASES.items():
        if n in aliases:
            return analyte, 0.99
    best = None
    for analyte, aliases in ANALYTE_ALIASES.items():
        for alias in aliases:
            if n.startswith(alias + " ") and (best is None or len(alias) > best[2]):
                best = (analyte, 0.85, len(alias))
    return (best[0], best[1]) if best else (None, 0.0)


def extract(text: str) -> ExtractionResult:
    result = ExtractionResult()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        negated = any(low.startswith(n) or f" {n}" in low for n in _NEGATION)
        uncertain = any(u in low for u in _UNCERTAINTY)

        parts = re.split(r"[:\t]|\s{2,}", line, maxsplit=1)
        if len(parts) != 2:
            m = re.match(r"(?P<label>[A-Za-z][A-Za-z0-9 /()\-]+?)\s+(?P<rest>-?\d.*)$", line)
            if not m:
                continue
            label, rest = m.group("label"), m.group("rest")
        else:
            label, rest = parts

        analyte, ctx = _match_analyte(label)
        if analyte is None:
            continue

        vm = _VALUE_UNIT_RE.search(rest)
        value: float | None = None
        unit = ""
        entity_conf = 0.3
        if vm:
            try:
                value = float(vm.group("value"))
                unit = (vm.group("unit") or "").strip()
                entity_conf = 0.95 if unit else 0.8
            except ValueError:
                value = None
        if negated:
            value = None
            entity_conf = min(entity_conf, 0.5)

        result.entities.append(
            Entity(
                kind="lab_value",
                analyte=analyte,
                text=line[:200],
                value=value,
                unit=unit,
                entity_confidence=round(entity_conf, 3),
                context_confidence=round(ctx, 3),
                negated=negated,
                uncertain=uncertain,
            )
        )
    if not result.entities:
        result.status = "NO_ENTITIES"
    return result
