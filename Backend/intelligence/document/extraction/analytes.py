"""Pull candidate result lines out of report text.

This is deliberately dumb and deterministic: a line-oriented regex that finds
``<label> <value> [unit] [flag] [reference]`` and records exactly what it saw,
with the character span it came from. It does not know what an analyte is, does
not convert anything, and does not decide whether a value is normal. Those are
later stages. Its one clinical-safety rule: a line it cannot parse cleanly is
skipped, never half-guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

EXTRACTOR = "regex-line"
EXTRACTOR_VERSION = "1.0"

_NUMBER = r"\d[\d,]*(?:\.\d+)?"

_LINE = re.compile(
    r"^\s*"
    r"(?P<label>[A-Za-z][A-Za-z0-9 ,()./%+\-]*?)"
    r"\s*[:\.…\-]?\s*"
    r"(?P<value>" + _NUMBER + r")"
    r"(?P<rest>[^\n]*)$"
)

#: Standalone tokens that mark a result as flagged on the report itself.
_FLAGS = {
    "h": "H", "hh": "HH", "hi": "H", "high": "H",
    "l": "L", "ll": "LL", "lo": "L", "low": "L",
    "a": "A", "abn": "A", "*": "*", "↑": "H", "↓": "L",
    "cl": "CRITICAL_LOW", "ch": "CRITICAL_HIGH",
}

#: Labels that are never analytes - metadata lines that happen to contain a
#: number. Matched case-insensitively against the start of the label.
_STOP_LABELS = (
    "page", "patient", "name", "age", "sex", "gender", "date", "sample",
    "specimen", "collected", "received", "reported", "printed", "method",
    "reference", "ref range", "ref", "biological ref", "units", "result",
    "test", "investigation", "report", "lab no", "uhid", "mrn", "accession",
    "doctor", "physician", "consultant", "phone", "fax", "address", "barcode",
    "comment", "note", "interpretation", "impression", "verified", "authori",
)

#: A unit token: a cell-count form like ``10^9/L`` / ``x10^3/uL`` / ``10*9/L``,
#: or an ordinary unit starting with a letter or ``%``. Never a bare number.
_UNIT_RE = re.compile(
    r"^(?:x?10[\^*]?\d+/[a-zµμ]+|[%A-Za-zµμ][A-Za-z0-9/^%*·.\-]*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RawExtraction:
    label: str
    value_text: str
    value: float | None
    unit: str
    reference_text: str
    printed_flag: str
    line: str
    page: int
    char_span: tuple[int, int]
    extraction_confidence: float
    extractor: str = EXTRACTOR
    extractor_version: str = EXTRACTOR_VERSION
    issues: tuple[str, ...] = field(default_factory=tuple)


def _looks_like_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 4 and all(c.isupper() for c in letters) and not any(
        ch.isdigit() for ch in line
    ):
        return True
    return False


def _page_of(offset: int, page_breaks: list[int]) -> int:
    page = 1
    for start in page_breaks:
        if offset >= start:
            page += 1
        else:
            break
    return page


def _parse_number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _split_rest(rest: str) -> tuple[str, str, str]:
    """rest -> (unit, printed_flag, reference_text)."""
    tokens = rest.strip().split()
    unit = ""
    flag = ""
    idx = 0

    if idx < len(tokens) and _UNIT_RE.match(tokens[idx]) and tokens[idx].lower() not in _FLAGS:
        # A bare alphabetic word that is really the flag ("High") shouldn't be
        # eaten as a unit; the _FLAGS check above handles the common ones.
        unit = tokens[idx]
        idx += 1

    if idx < len(tokens) and tokens[idx].lower().strip("()") in _FLAGS:
        flag = _FLAGS[tokens[idx].lower().strip("()")]
        idx += 1

    reference = " ".join(tokens[idx:]).strip()
    # A leading flag can also appear *after* the reference on some layouts.
    if not flag and reference:
        parts = reference.split()
        if parts[-1].lower().strip("()") in _FLAGS:
            flag = _FLAGS[parts[-1].lower().strip("()")]
            reference = " ".join(parts[:-1]).strip()
    return unit, flag, reference


def extract_raw_values(
    text: str, *, page_breaks: list[int] | None = None
) -> list[RawExtraction]:
    page_breaks = page_breaks or []
    out: list[RawExtraction] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped or _looks_like_heading(stripped):
            continue

        match = _LINE.match(stripped)
        if not match:
            continue

        label = match["label"].strip(" .:-…")
        if not label or len(label) < 2:
            continue
        low = label.lower()
        if any(low == stop or low.startswith(stop + " ") for stop in _STOP_LABELS):
            continue

        value = _parse_number(match["value"])
        unit, flag, reference = _split_rest(match["rest"])

        issues: list[str] = []
        confidence = 0.85
        if value is None:
            issues.append("value is not numeric")
            confidence -= 0.35
        if not unit:
            issues.append("no unit on the line")
            confidence -= 0.15
        if not reference:
            confidence -= 0.05

        span_start = start + line.index(stripped)
        out.append(
            RawExtraction(
                label=label,
                value_text=match["value"],
                value=value,
                unit=unit,
                reference_text=reference,
                printed_flag=flag,
                line=stripped,
                page=_page_of(span_start, page_breaks),
                char_span=(span_start, span_start + len(stripped)),
                extraction_confidence=round(max(confidence, 0.1), 3),
                issues=tuple(issues),
            )
        )
    return out
