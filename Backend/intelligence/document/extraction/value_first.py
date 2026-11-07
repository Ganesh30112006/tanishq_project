"""Tables whose text comes out with the result in front of the test's name.

Plain extraction of some PDFs (Dr Lal PathLabs' are the ones seen) returns each
row in the order the file stores it, not the order it prints::

    Test Name Results Units Bio. Ref. Interval
    0.86Creatinine
    (Compensated Jaffes reaction, IDMS traceable)
     0.67 - 1.17mg/dL
    11.00Urea Nitrogen  Blood 6.00 - 20.00mg/dL

The result is stuck to the name and the unit to the range, so the row can only
be read as a whole. It is read when every part is where that shape puts it:

* the laboratory's own column titles opened the table, on this page;
* the number touches the name, with no space. A blank result prints no number,
  so it can never borrow one;
* a range and a unit close the row, on the same line or the next, with at most
  one bracketed method line between. Anything else there means the row is not
  this shape, and its number is not offered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER = r"\d[\d,]*(?:\.\d+)?"
#: The unit must start with a letter or %, so that a unit glued to a range can
#: be told from the range: "11.010^9/L" could split in two ways, and is refused.
_RANGE_AND_UNIT = (
    r"(?P<range>[<>≤≥]?\s*" + _NUMBER + r"(?:\s*-\s*" + _NUMBER + r")?)"
    r"\s*(?P<unit>[A-Za-zµμ%]\S*)"
)

TABLE_HEADER = re.compile(r"^test\s+name\s+results?\s+units?\s+bio\b", re.IGNORECASE)
_GLUED = re.compile(r"^(?P<value>" + _NUMBER + r")(?P<rest>[A-Za-z].*)$")
_ON_THE_LINE = re.compile(r"^(?P<name>.*?)\s+" + _RANGE_AND_UNIT + r"$")
_ON_ITS_OWN = re.compile(r"^" + _RANGE_AND_UNIT + r"$")
_METHOD = re.compile(r"^\(.*\)$")


@dataclass(frozen=True, slots=True)
class Row:
    name: str
    value_text: str
    #: False when no range and unit closed the row, so the number is not read.
    complete: bool
    reference: str
    unit: str
    source: str
    start: int
    end: int


@dataclass(slots=True)
class _Open:
    value_text: str
    name: str
    lines: list[str]
    start: int
    end: int
    method_seen: bool = False


class Table:
    """Feed it a table's lines in order; it returns each row as it closes."""

    def __init__(self) -> None:
        self._open: _Open | None = None

    def feed(self, line: str, start: int) -> tuple[bool, list[Row]]:
        """(was the line part of a row, rows closed by it)."""
        end = start + len(line)
        glued = _GLUED.match(line)
        if glued is not None:
            closed = self.flush()
            on_line = _ON_THE_LINE.match(glued["rest"])
            if on_line is not None:
                closed.append(_row(
                    on_line["name"], glued["value"], on_line, line, start, end,
                ))
            else:
                self._open = _Open(glued["value"], glued["rest"], [line], start, end)
            return True, closed

        current = self._open
        if current is None:
            return False, []
        alone = _ON_ITS_OWN.match(line)
        if alone is not None:
            self._open = None
            source = "\n".join([*current.lines, line])
            return True, [_row(current.name, current.value_text, alone, source, current.start, end)]
        if _METHOD.match(line) and not current.method_seen:
            current.method_seen = True
            current.lines.append(line)
            current.end = end
            return True, []
        return False, self.flush()

    def flush(self) -> list[Row]:
        """Close a row still waiting for its range: its number is not read."""
        current, self._open = self._open, None
        if current is None:
            return []
        return [Row(
            name=_clean(current.name), value_text=current.value_text, complete=False,
            reference="", unit="", source="\n".join(current.lines),
            start=current.start, end=current.end,
        )]


def _clean(name: str) -> str:
    return " ".join(name.split())


def _row(name: str, value: str, closing: re.Match, source: str, start: int, end: int) -> Row:
    return Row(
        name=_clean(name), value_text=value, complete=True,
        reference=_clean(closing["range"]), unit=closing["unit"],
        source=source, start=start, end=end,
    )
