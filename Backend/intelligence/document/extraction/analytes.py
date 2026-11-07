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
from dataclasses import dataclass, field, replace
from datetime import date

from intelligence.document.extraction import cumulative, value_first
from intelligence.document.normalization.analytes import canonical_analyte
from intelligence.document.normalization.units import normalize_unit_token

EXTRACTOR = "regex-line"
#: 1.2: unit after the flag, "/c.mm"; 1.3: cumulative columns, "10~9/L";
#: 1.4: wrapped date tables, where a name sits above its numbers;
#: 1.5: result-first tables, and a name continued on the next line;
#: 1.6: range before unit, a flag beside the name, unit-first rows.
EXTRACTOR_VERSION = "1.6"

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
    # A remark, not a direction: it never disagrees with the range.
    "borderline": "BORDERLINE",
}

#: Flags a laboratory prints between the test's name and its result.
_FLAGS_BESIDE_NAME = frozenset({"h", "hh", "high", "l", "ll", "low"})

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
    r"^(?:x?10[\^*~]?\d+/[a-zµμ]+|/[a-zµμ][a-zµμ.]*|[%A-Za-zµμ][A-Za-z0-9/^%*·.µμ\-]*)$",
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

#: ...unless what follows is plainly a reference interval. "13.0 - 17.0" is a
#: range, not a competing result: the dash says so, and no OCR split produces
#: one. Without this the guard refuses a line whose result is perfectly clear
#: and whose reference range is printed beside it in a column of its own.
_TRAILING_INTERVAL = re.compile(
    r"^[\s(\[]*" + _NUMBER + r"\s*[-‐-―−]\s*" + _NUMBER + r"\s*[)\]]*\s*$"
)

#: A dash and a number straight after the first number: that number began a range.
_DASH_THEN_NUMBER = re.compile(r"^\s*[-‐-―−]\s*\d")

#: A range written as a dashed interval or a one-sided limit. A bare second
#: number is never a range: that is the OCR split the guard above refuses.
_RANGE = (
    r"(?:" + _NUMBER + r"\s*[-‐-―−]\s*" + _NUMBER + r"|[<>≤≥]\s*" + _NUMBER + r")"
)

#: What follows the result on many Indian layouts: an optional flag, the range,
#: then the unit in the last column. "15 11.5 - 18.0 gm%", "8.5 H 6.2 - 8.0 gm/dL".
_RANGE_THEN_UNIT = re.compile(
    r"^\s*(?:(?P<flag>[A-Za-z]+)\s+)?(?P<range>" + _RANGE + r")\s+(?P<unit>\S+)\s*$"
)

#: Some PDFs store a row with the result last, and the method touching the range:
#: "Hemoglobin g/dL 13.0 - 16.5Colorimetric 14.5". The method has to be there. With
#: nothing between them, the range and the result could be split in more than one way.
_UNIT_FIRST_ROW = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 ,()./%+\-]*?)"
    r"(?:\s+(?P<flag>[HL]))?"
    r"\s+(?P<unit>\S+)\s+(?P<range>" + _RANGE + r")"
    r"[A-Za-z][A-Za-z .,()/\-]*\s+(?P<value>" + _NUMBER + r")$"
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
    #: On a cumulative report, which dated column the value was read from.
    column: str = ""


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
        # Many Indian layouts print the flag beside the value and the unit in
        # its own column after it: "10.2 L gm/dl". Without this the unit was
        # swallowed into the reference text and the line read as unitless. A
        # word wrongly taken as a unit here is not a unit the table knows, so
        # the value is held as unconvertible - never misread.
        if not unit and idx < len(tokens) and _UNIT_RE.match(tokens[idx]) \
                and tokens[idx].lower() not in _FLAGS:
            unit = tokens[idx]
            idx += 1

    reference = " ".join(tokens[idx:]).strip()
    # A leading flag can also appear *after* the reference on some layouts.
    if not flag and reference:
        parts = reference.split()
        if parts[-1].lower().strip("()") in _FLAGS:
            flag = _FLAGS[parts[-1].lower().strip("()")]
            reference = " ".join(parts[:-1]).strip()
    return unit, flag, reference


def _range_then_unit(rest: str) -> tuple[str, str, str] | None:
    """(unit, flag, reference) where the range comes before the unit, else None."""
    match = _RANGE_THEN_UNIT.match(rest)
    if match is None or not _UNIT_RE.match(match["unit"]):
        return None
    if match["unit"].lower() in _FLAGS:
        return None
    word = (match["flag"] or "").lower()
    if word and word not in _FLAGS:
        return None
    return match["unit"], _FLAGS.get(word, ""), " ".join(match["range"].split())


def _flag_beside_name(label: str) -> tuple[str, str]:
    """(label, flag) for "LYMPHOCYTE L", where the flag sits before the result.

    Without this the row's name is unknown, so exactly the rows a laboratory
    marked abnormal are lost while the normal rows around them are read. Only
    when the whole label is unknown and the name without the flag is a known test.
    """
    head, _, last = label.rpartition(" ")
    if (
        head
        and last.lower() in _FLAGS_BESIDE_NAME
        and canonical_analyte(label) is None
        and canonical_analyte(head) is not None
    ):
        return head, _FLAGS[last.lower()]
    return label, ""


def _unit_first_row(line: str) -> RawExtraction | None:
    """A row printed as name, unit, range and method, then result. Known tests only."""
    match = _UNIT_FIRST_ROW.match(line)
    if match is None:
        return None
    label = match["label"].strip(" .:-…")
    if canonical_analyte(label) is None or normalize_unit_token(match["unit"]) is None:
        return None
    flag = match["flag"] or ""
    return RawExtraction(
        label=label, value_text=match["value"], value=_parse_number(match["value"]),
        unit=match["unit"], reference_text=" ".join(match["range"].split()),
        printed_flag=_FLAGS[flag.lower()] if flag else "", line=line,
        page=1, char_span=(0, 0), extraction_confidence=0.8,
    )


_CUMULATIVE_ROW = re.compile(
    r"^\s*"
    r"(?P<label>[A-Za-z][A-Za-z0-9 ,()./%+\-]*?)"
    + _SEPARATOR
    + r"(?P<values>" + _NUMBER + r"(?:\s+" + _NUMBER + r")+)"
    r"(?P<rest>\s+[^\n]*)$"
)


def _cumulative_row(line: str, columns: tuple[int, int, date]) -> RawExtraction | None:
    """The newest column of a cumulative row - see :mod:`.cumulative`."""
    index, count, dated = columns
    match = _CUMULATIVE_ROW.match(line)
    if match is None:
        return None
    values = match["values"].split()
    if len(values) != count:
        return None  # a blank cell: which column is missing cannot be told
    label = match["label"].strip(" .:-…")
    low = label.lower()
    if len(label) < 2 or any(low == s or low.startswith(s + " ") for s in _STOP_LABELS):
        return None
    first = match["rest"].split()[0]
    if not _UNIT_RE.match(first) or first.lower() in _FLAGS:
        return None  # the unit must follow the last column directly
    unit, flag, reference = _split_rest(match["rest"])
    value_text = values[index]
    return RawExtraction(
        label=label, value_text=value_text, value=_parse_number(value_text),
        unit=unit, reference_text=reference, printed_flag=flag, line=line,
        page=1, char_span=(0, 0),
        extraction_confidence=0.8 if reference else 0.75,
        column=f"{dated.isoformat()} (column {index + 1} of {count})",
    )


#: The numbers of a wrapped table's row, and what follows them.
_NUMBERS_ROW = re.compile(
    r"^(?P<values>" + _NUMBER + r"(?:\s+" + _NUMBER + r")*)(?P<rest>\s+\S.*)$"
)
#: What a row of numbers can start with: a number, then another number, a
#: range's dash or a unit. That excludes a name starting with a digit, such as
#: "25 Hydroxy, Vitamin D".
_NUMBER_START = re.compile(
    r"^" + _NUMBER + r"(?:$|\s+(?:" + _NUMBER + r"(?:\s|$)|[-‐-―−<>≤≥]|[^\s,]+(?:\s|$)))"
)
#: A reference interval and nothing else. Words here mean the line is a sentence.
_ONLY_INTERVAL = re.compile(r"^[\d\s.,:<>≤≥=\-‐-―−]*$")

#: Name, a wrapped second line of the name, assay method.
_MAX_LINES_ABOVE = 3

#: Assay methods printed in capitals under a test's name. Only these, and only
#: with a name waiting above: any other capitalised line is a heading.
_CAPITALISED_METHODS = frozenset({"clia", "hplc"})


def _name_above(above: list[str]) -> tuple[str, bool]:
    """(label, may this row's value be read) for the lines above a row of numbers.

    The name must start on the first line after the previous row, so a name can
    never be picked out from further down. Any later line being a test name in
    its own right means an empty result above: the numbers may belong to either,
    so neither gets them.
    """
    first_two = " ".join(above[:2])
    if canonical_analyte(above[0]) is not None:
        label, others = above[0], above[1:]
    elif len(above) > 1 and canonical_analyte(first_two) is not None:
        label, others = first_two, above[2:]
    else:
        # No recognised name. It stays visible as an unrecognised test.
        label, others = first_two, above
    return label, not any(canonical_analyte(line) is not None for line in others)


def _wrapped_row(
    line: str, above: list[str], columns: tuple[int, int, date]
) -> RawExtraction | None:
    """A row of numbers in a wrapped table, or None if the line is not one."""
    if not above or len(above) > _MAX_LINES_ABOVE or _NUMBER_START.match(line) is None:
        return None
    index, count, dated = columns
    label, readable = _name_above(above)
    refused = RawExtraction(
        label=label, value_text="", value=None, unit="", reference_text="", printed_flag="",
        line="\n".join([*above, line]), page=1, char_span=(0, 0), extraction_confidence=0.1,
        issues=("the row does not fit its dated columns, so its result cannot be established",),
    )
    match = _NUMBERS_ROW.match(line)
    if match is None or not readable:
        return refused
    values = match["values"].split()
    rest = match["rest"].split()
    if len(values) != count or not _UNIT_RE.match(rest[0]) or rest[0].lower() in _FLAGS:
        return refused
    reference = " ".join(rest[1:])
    if not _ONLY_INTERVAL.match(reference):
        return refused
    return replace(
        refused, value_text=values[index], value=_parse_number(values[index]), unit=rest[0],
        reference_text=reference, extraction_confidence=0.8 if reference else 0.75,
        column=f"{dated.isoformat()} (column {index + 1} of {count})", issues=(),
    )


def _value_first_row(row: value_first.Row, page_breaks: list[int]) -> RawExtraction | None:
    """A closed result-first row. One left open is shown only if it names a known test."""
    if not row.complete and canonical_analyte(row.name) is None:
        return None
    return RawExtraction(
        label=row.name,
        value_text=row.value_text if row.complete else "",
        value=_parse_number(row.value_text) if row.complete else None,
        unit=row.unit, reference_text=row.reference, printed_flag="", line=row.source,
        page=_page_of(row.start, page_breaks), char_span=(row.start, row.end),
        extraction_confidence=0.8 if row.complete else 0.1,
        issues=() if row.complete else (
            "no range and unit closed the row, so its result cannot be established",
        ),
    )


def _continued_name(label: str, next_line: str) -> str | None:
    """The whole name, where it runs onto the line after the result.

    "Glycosylated 5.40 %" then "Haemoglobin(Hb A1c)". Only for a label that means
    nothing alone and a whole that is a known test, so it can only ever name a
    row that would otherwise be unrecognised.
    """
    if canonical_analyte(label) is not None or not next_line:
        return None
    whole = f"{label} {next_line}"
    return whole if canonical_analyte(whole) is not None else None


def extract_raw_values(
    text: str, *, page_breaks: list[int] | None = None
) -> list[RawExtraction]:
    page_breaks = page_breaks or []
    out: list[RawExtraction] = []
    offset = 0
    collected = cumulative.collection_date(text)
    columns: tuple[int, int, date] | None = None  # the open cumulative header
    wrapped = False  # was it a wrapped header, where a name sits above its numbers?
    above: list[tuple[int, str]] = []  # the lines since the wrapped table's last row
    header_end = -1
    result_first: value_first.Table | None = None  # the open result-first table
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped or index <= header_end:
            continue
        if value_first.TABLE_HEADER.match(stripped):
            if result_first is not None:
                closed = result_first.flush()
                out.extend(r for r in (_value_first_row(x, page_breaks) for x in closed) if r)
            result_first = value_first.Table()
            continue
        if result_first is not None:
            if cumulative.ends_context(stripped):
                consumed, closed = False, result_first.flush()
                result_first = None
            else:
                consumed, closed = result_first.feed(stripped, start + line.index(stripped))
            out.extend(r for r in (_value_first_row(x, page_breaks) for x in closed) if r)
            if consumed:
                continue
        opened = cumulative.wrapped_header(lines, index, collected)
        if opened is not None:
            header_end, columns = opened
            wrapped, above = True, []
            continue
        header = cumulative.header_column(stripped, collected)
        if header is not None:
            columns, wrapped = header, False
            continue
        # A short test name in capitals ("MCHC") and the method under a name
        # ("CLIA") are rows of the table, not headings.
        heading = _looks_like_heading(stripped) and not (
            wrapped and (
                canonical_analyte(stripped) is not None
                or (above and stripped.lower() in _CAPITALISED_METHODS)
            )
        )
        if heading or cumulative.ends_context(stripped):
            columns, wrapped, above = None, False, []
        if heading:
            continue

        if wrapped and columns is not None:
            row = _wrapped_row(stripped, [text for _, text in above], columns)
            if row is not None:
                span_start = above[0][0]
                out.append(replace(
                    row, page=_page_of(span_start, page_breaks),
                    char_span=(span_start, start + line.index(stripped) + len(stripped)),
                ))
                above = []
                continue

        if columns is not None:
            row = _cumulative_row(stripped, columns)
            if row is not None:
                span_start = start + line.index(stripped)
                out.append(replace(
                    row, page=_page_of(span_start, page_breaks),
                    char_span=(span_start, span_start + len(stripped)),
                ))
                continue

        row = _unit_first_row(stripped)
        if row is not None:
            above = []
            span_start = start + line.index(stripped)
            out.append(replace(
                row, page=_page_of(span_start, page_breaks),
                char_span=(span_start, span_start + len(stripped)),
            ))
            continue

        censored = _CENSORED.match(stripped)
        match = _LINE.match(stripped)

        if censored is not None and match is not None:
            # Both shapes fit the line, and which one it really is depends on
            # where the bound sits relative to the result.
            #
            #   TSH  < 0.01 uIU/mL          the bound IS the result
            #   Cholesterol 228 mg/dL < 200 the bound is the reference range
            #
            # The result column is established first and the reference range
            # is read separately from what follows it. Before this, the
            # censored rule won unconditionally, so an ordinary result printed
            # against a one-sided target - which is how most lipid panels
            # print theirs - lost its value entirely: the label swallowed
            # "Cholesterol 228 mg/dL" and the parser reported the target as a
            # censored result.
            if match.start("value") < censored.start("bound"):
                censored = None

        if not match and not censored:
            if wrapped:
                above.append((start + line.index(stripped), stripped))
            continue

        above = []
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
            unit, flag, reference = _range_then_unit(match["rest"]) or _split_rest(match["rest"])

            if _DASH_THEN_NUMBER.match(match["rest"]):
                # "Serum Sodium 136-146 mmol/L": a range with no result, usually
                # in the notes under the table. Its low end is not a result, and
                # counted as one it conflicts with the real result above.
                issues.append("the line gives a range and no result")
                value = None
                confidence -= 0.5

            if (
                not unit
                and _SECOND_NUMBER.match(match["rest"])
                and not _TRAILING_INTERVAL.match(match["rest"])
            ):
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

        label, flag_by_name = _flag_beside_name(label)
        flag = flag or flag_by_name

        span_start = start + line.index(stripped)
        span_end = span_start + len(stripped)
        source_line = stripped
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        whole_name = _continued_name(label, following)
        if whole_name is not None:
            label = whole_name
            source_line = f"{stripped}\n{following}"
            span_end = offset + lines[index + 1].index(following) + len(following)
        out.append(
            RawExtraction(
                label=label,
                value_text=value_text,
                value=value,
                unit=unit,
                reference_text=reference,
                printed_flag=flag,
                line=source_line,
                page=_page_of(span_start, page_breaks),
                char_span=(span_start, span_end),
                extraction_confidence=round(max(confidence, 0.1), 3),
                issues=tuple(issues),
            )
        )
    if result_first is not None:
        closed = result_first.flush()
        out.extend(r for r in (_value_first_row(x, page_breaks) for x in closed) if r)
    return out
