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
EXTRACTOR_VERSION = "1.1"

_NUMBER = r"\d[\d,]*(?:\.\d+)?"

#: A result the laboratory reported as beyond its measuring range: "< 0.01",
#: "> 100". These are clinically meaningful - a TSH of <0.01 is a suppressed
#: TSH - but they are not numbers, and treating "<0.01" as 0.01 would invent a
#: precision the assay explicitly declined to give. They are extracted with no
#: numeric value and marked, so the report does not silently lose them.
_CENSORED = re.compile(
    r"^\s*(?P<label>[A-Za-z][A-Za-z0-9 ,()./%+\-]*?)"
    r"(?:\s*[:\.…=]\s*|\s+)"
    r"(?P<bound>[<>≤≥]\s*" + _NUMBER + r")"
    r"(?P<rest>.*)$"
)

#: What may sit between the label and the value. There must be *something* -
#: whitespace, or a punctuation separator. Allowing nothing here is how
#: ``HbA1c 6.2 %`` used to read as the analyte "HbA" with the value 1 and the
#: unit "c": the non-greedy label stopped at the first digit it could. Many
#: real analyte names carry a digit (HbA1c, Free T3, CO2, Vitamin B12), so the
#: digit cannot be a boundary - the separator is.
_SEPARATOR = r"(?:\s*[:\.…\-=]\s*|\s+)"

_LINE = re.compile(
    r"^\s*"
    r"(?P<label>[A-Za-z][A-Za-z0-9 ,()./%+\-]*?)"
    + _SEPARATOR
    + r"(?P<value>" + _NUMBER + r")"
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
#: a per-volume form like ``/uL``, or an ordinary unit starting with a letter
#: or ``%``. Never a bare number.
_UNIT_RE = re.compile(
    r"^(?:x?10[\^*]?\d+/[a-zµμ]+|/[a-zµμ]+|[%A-Za-zµμ][A-Za-z0-9/^%*·.\-]*)$",
    re.IGNORECASE,
)

#: A second number sitting where a unit should be. Two shapes produce this and
#: both are dangerous: OCR splitting one number in two ("13.4" -> "1 3.4"), and
#: a line carrying two results ("1.2 / 1.4"). In each case the first number was
#: taken as the value and the rest discarded, which is how a haemoglobin of
#: 13.4 became a haemoglobin of 1. The line is extracted with no value at all
#: and flagged, because a second number means we do not know which is the
#: result.
_SECOND_NUMBER = re.compile(r"^[\s/,;|]*" + _NUMBER + r"(?:\s|$|[^\w%/^*])")


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

        censored = _CENSORED.match(stripped)
        match = _LINE.match(stripped)
        if not match and not censored:
            continue

        source = censored or match
        label = source["label"].strip(" .:-…")
        if not label or len(label) < 2:
            continue
        low = label.lower()
        if any(low == stop or low.startswith(stop + " ") for stop in _STOP_LABELS):
            continue

        issues: list[str] = []
        confidence = 0.85

        if censored is not None:
            # "< 0.01" is a real result and not a number. Reading it as 0.01
            # would invent a precision the assay explicitly declined to give,
            # and dropping the line would lose a clinically important result -
            # a TSH of <0.01 is a suppressed TSH. So it is carried with no
            # numeric value, and the text is preserved verbatim.
            value_text = re.sub(r"\s+", "", censored["bound"])
            value = None
            unit, flag, reference = _split_rest(censored["rest"])
            issues.append(
                f"result reported as {value_text}, which is a bound rather "
                f"than a measured value"
            )
            confidence -= 0.2
        else:
            value_text = match["value"]
            value = _parse_number(value_text)
            unit, flag, reference = _split_rest(match["rest"])

            if not unit and _SECOND_NUMBER.match(match["rest"]):
                # Another number where the unit should be. Either OCR split one
                # number in two, or the line carries two results. Both mean we
                # do not know which number is the result, so none is offered.
                issues.append(
                    "a second number follows the value with no unit between "
                    "them, so which number is the result cannot be established"
                )
                value = None
                confidence -= 0.5

            if value is None and not issues:
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
                value_text=value_text,
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
