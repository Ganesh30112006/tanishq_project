"""Cumulative reports: one row, several dates' results.

Some laboratories print a patient's earlier results beside today's, one column
per collection date::

    Date        01/Sep/2021  27/Aug/21  22/Aug/21   Unit   Bio Ref Interval
    Haemoglobin 11.8         11.6       12.0        g/dl   12.0 - 15.0

The line parser refuses such a row - more than one number, so which one is the
result cannot be known from the row alone. The header says which: the column to
read is the one dated with this report's own collection date. It is read only
when every link in that chain holds:

* the header's dates parse unambiguously, and are all different;
* the report prints its collection date, and it is the newest date in the
  header - an older column is history, never this report's result;
* the row carries exactly one number per date, and a unit straight after the
  last of them. A blank cell leaves the row one short, and a short row is
  refused rather than realigned, because the reader cannot tell which column
  is the blank one.

Anything else is left to the line parser, which refuses the row as before.

Plain extraction of the same report can break it apart: the header wraps over a
line per date and time, and each test's name sits above its numbers with the
assay method between them::

    Date 14/Dec/2025
    09:47AM
    01/Jun/25
    07:49AM
    Unit Bio Ref Interval
    Haemoglobin
    Modified cyanmethemoglobin
    15.1 15.5 g/dl 13.0 - 17.0

The same chain applies to such a header, which may name a single date. Only
inside one may a name be paired with numbers on a later line; the pairing rules
are in ``analytes._name_above``. Nowhere else is a bare row of numbers read.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"), start=1,
    )
}

#: A date's day and month, which anchor it. The year is whatever digits sit
#: between this anchor and the next: the columns are often printed so close
#: that layout extraction runs them together ("01/Sep/202127/Aug/21").
_DAY_MONTH = re.compile(r"(\d{1,2})/([A-Za-z]{3})/")
_YEAR = re.compile(r"\d+")
_HEADER = re.compile(r"^date\b\s*(?P<dates>.*)$", re.IGNORECASE)
_WRAPPED_START = re.compile(r"^date\s+(?P<date>\S+)$", re.IGNORECASE)
_TIME = re.compile(r"^\d{1,2}:\d{2}\s*[ap]m$", re.IGNORECASE)
_COLLECTION = re.compile(r"collection\s+date(?:\s*/\s*time)?\s*:?\s*", re.IGNORECASE)

#: Lines after which a cumulative header no longer describes the rows.
_COLUMN_HEADER = re.compile(r"\bunits?\b.*\b(?:ref|reference|interval)\b", re.IGNORECASE)
_PAGE_END = re.compile(r"\bpage\s+\d+\s+of\s+\d+\b|\bend\s+of\s+report\b", re.IGNORECASE)


def parse_dates(segment: str) -> list[date] | None:
    """Every ``dd/Mon/yy`` or ``dd/Mon/yyyy`` date in ``segment``, or None.

    None whenever any part is uncertain: a year that is neither two digits
    nor a 19xx/20xx year, anything but space between two dates, a date that
    does not exist. A header is used whole or not at all.
    """
    anchors = list(_DAY_MONTH.finditer(segment))
    if not anchors or segment[: anchors[0].start()].strip():
        return None
    dates: list[date] = []
    for i, anchor in enumerate(anchors):
        last = i + 1 == len(anchors)
        tail = segment[anchor.end(): None if last else anchors[i + 1].start()]
        year_match = _YEAR.match(tail)
        if year_match is None:
            return None
        if not last and tail[year_match.end():].strip():
            return None
        year_text = year_match.group()
        if len(year_text) == 2:
            year = 2000 + int(year_text)
        elif len(year_text) == 4 and year_text[:2] in ("19", "20"):
            year = int(year_text)
        else:
            return None
        month = _MONTHS.get(anchor.group(2).lower())
        if month is None:
            return None
        try:
            dates.append(date(year, month, int(anchor.group(1))))
        except ValueError:
            return None
    return dates


def collection_date(text: str) -> date | None:
    """The report's own collection date, if it prints one consistently."""
    found: set[date] = set()
    for match in _COLLECTION.finditer(text):
        window = text[match.end(): match.end() + 12].split()
        parsed = parse_dates(window[0]) if window else None
        if parsed is None or len(parsed) != 1:
            return None
        found.add(parsed[0])
    return found.pop() if len(found) == 1 else None


def header_column(line: str, collected: date | None) -> tuple[int, int, date] | None:
    """(column to read, number of columns, its date) for a cumulative header.

    None when the line is not a header of two or more dates, or when the
    column cannot be established.
    """
    match = _HEADER.match(line.strip())
    if match is None or collected is None:
        return None
    # The header ends where the column titles begin.
    segment = re.split(r"\bunits?\b", match["dates"], maxsplit=1, flags=re.IGNORECASE)[0]
    dates = parse_dates(segment.strip())
    if dates is None or len(dates) < 2 or len(set(dates)) != len(dates):
        return None
    newest = max(dates)
    if newest != collected:
        return None
    return dates.index(newest), len(dates), newest


def wrapped_header(
    lines: list[str], start: int, collected: date | None
) -> tuple[int, tuple[int, int, date]] | None:
    """(index of the header's last line, its columns) for a header split over lines.

    ``Date <date>`` opens it, only dates and times may follow, and a line of
    column titles ends it. Anything else means this is not a header, so None.
    """
    match = _WRAPPED_START.match(lines[start].strip())
    if match is None or collected is None:
        return None
    dates = parse_dates(match["date"])
    if dates is None or len(dates) != 1:
        return None
    for index in range(start + 1, len(lines)):
        line = lines[index].strip()
        if _TIME.match(line):
            continue
        if _COLUMN_HEADER.search(line):
            if len(set(dates)) != len(dates) or max(dates) != collected:
                return None
            # "Unit Bio Ref" can leave its last word on the next line.
            following = lines[index + 1].strip().lower() if index + 1 < len(lines) else ""
            end = index + 1 if following == "interval" else index
            return end, (dates.index(collected), len(dates), collected)
        parsed = parse_dates(line)
        if parsed is None or len(parsed) != 1:
            return None
        dates.extend(parsed)
    return None


def ends_context(line: str) -> bool:
    """Does this line close the table a cumulative header described?"""
    return bool(_COLUMN_HEADER.search(line) or _PAGE_END.search(line))
