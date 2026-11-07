"""Reports that carry several panels, and the sample each section is about.

A health-check package prints a lipid profile, a liver panel, a kidney panel
and a blood count in one document. No single report type fits it, so the
classifier abstains - correctly - and until 2026-11 nothing on it was read. On
fourteen sample reports that Indian laboratories publish, nine were such
packages, and every one yielded no values.

Such a document is read when it says so itself: it must print at least two
headings that each name a blood panel ("Lipid Profile, Serum", "Kidney Function
Test (KFT)"), and nothing is read above the first of them. Each value is then
held to its own panel's plausibility bounds. A document that also scores as a
narrative - a discharge summary, a clinical note, a prescription, a radiology
report - is never read this way, because the numbers in a narrative are as
often history as they are results.

The sections also say which sample a value was measured in. "Creatinine
85 mg/dL" under a urine heading is a urine creatinine; read as a serum one it
is a patient in renal failure. A value under a heading that names a non-blood
sample is therefore never given a blood analyte's identity - on every report,
not only multi-panel ones.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from intelligence.document.classification.keyword import _MATCHERS, _MIN_SCORE, _SIGNALS
from intelligence.document.contracts import (
    ClassificationResult,
    ClassificationStatus,
    ReportType,
)
from intelligence.document.extraction import extract_raw_values

#: Panels measured in blood, which a multi-panel report is made of.
BLOOD_PANELS = frozenset({
    ReportType.CBC, ReportType.LIPID_PROFILE, ReportType.GLUCOSE,
    ReportType.HBA1C, ReportType.LIVER_FUNCTION, ReportType.KIDNEY_FUNCTION,
    ReportType.THYROID, ReportType.ELECTROLYTES,
})

#: Document types whose numbers are not a results table.
NARRATIVE = frozenset({
    ReportType.RADIOLOGY, ReportType.PRESCRIPTION,
    ReportType.DISCHARGE_SUMMARY, ReportType.CLINICAL_NOTE,
})

#: Analytes that are measured in urine, and so may be read under a urine
#: heading. Every other analyte is a blood one.
URINE_ANALYTES = frozenset({"urine_albumin_creatinine_ratio"})

#: A term this heavy names a panel rather than one of its analytes.
_PANEL_NAME_WEIGHT = 4

#: Headings that name a panel in words the classifier's own terms do not use,
#: as Dr Lal PathLabs prints them.
_EXTRA_PANEL_HEADINGS = {
    ReportType.LIPID_PROFILE: (re.compile(r"\blipid\s+screen\b"),),
    ReportType.LIVER_FUNCTION: (re.compile(r"\bliver\s*(?:&|and)\s*kidney\s+panel\b"),),
    ReportType.KIDNEY_FUNCTION: (re.compile(r"\bliver\s*(?:&|and)\s*kidney\s+panel\b"),),
    ReportType.GLUCOSE: (re.compile(r"\bglucose,?\s+fasting\b"),),
}
_HEADING_MAX_WORDS = 12

_NON_BLOOD = re.compile(
    r"(?<![a-z])(?:urine|urinary|stool|faecal|fecal|faeces|feces|csf|"
    r"cerebrospinal|pleural|ascitic|peritoneal|synovial|semen|seminal|sputum|"
    r"swab|body\s+fluid)(?![a-z])"
)
#: Words that put a section back in blood. Deliberately not the bare word
#: "blood": a urine routine prints "Blood  Nil" as one of its own rows.
_BLOOD = re.compile(
    r"(?<![a-z])(?:serum|plasma|whole\s+blood|edta|fluoride|haematology|"
    r"hematology|biochemistry)(?![a-z])"
)

_PANEL_NAMES = {
    report_type: tuple(
        pattern
        for (pattern, weight), term in zip(_MATCHERS[report_type], _SIGNALS[report_type], strict=True)
        if weight >= _PANEL_NAME_WEIGHT and term
    ) + _EXTRA_PANEL_HEADINGS.get(report_type, ())
    for report_type in BLOOD_PANELS
}


@dataclass(frozen=True, slots=True)
class Heading:
    offset: int
    text: str
    #: The blood panels this heading names.
    panels: frozenset[ReportType]
    #: True when it names a non-blood sample, False when a blood one, None
    #: when it names neither.
    non_blood: bool | None


def headings(text: str) -> list[Heading]:
    """Every heading line that names a panel or a sample, in order."""
    out: list[Heading] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped or len(stripped.split()) > _HEADING_MAX_WORDS:
            continue
        if extract_raw_values(stripped):
            continue  # a result row, not a heading
        lowered = stripped.lower()
        panels = frozenset(
            report_type
            for report_type, patterns in _PANEL_NAMES.items()
            if any(p.search(lowered) for p in patterns)
        )
        non_blood: bool | None = None
        if _NON_BLOOD.search(lowered):
            non_blood = True  # a non-blood word wins over a blood one
        elif panels or _BLOOD.search(lowered):
            non_blood = False
        if panels or non_blood is not None:
            out.append(Heading(start, stripped, panels, non_blood))
    return out


def multi_panel(
    text: str, classification: ClassificationResult, marks: list[Heading]
) -> tuple[ReportType, ...]:
    """The panels of a multi-panel laboratory report, or () if it is not one."""
    named: set[ReportType] = set()
    for mark in marks:
        named |= mark.panels
    if classification.status is ClassificationStatus.REVIEW_REQUIRED:
        if classification.reason != "classification_margin_not_met":
            return ()
    elif classification.status is ClassificationStatus.CLASSIFIED:
        # A package whose notes lean on one panel can win the vote outright: a
        # long lipid treatment-goal table made one a "lipid report", which held
        # its liver and kidney results to the wrong report's schema. The winner
        # must itself be one of the panels the document's headings name.
        if classification.report_type not in named:
            return ()
    else:
        return ()
    if any(classification.signals.get(t.value, 0) >= _MIN_SCORE for t in NARRATIVE):
        return ()
    if len(named) < 2:
        return ()
    return tuple(sorted(named, key=lambda rt: rt.value))


def first_panel_offset(marks: list[Heading]) -> int | None:
    return next((m.offset for m in marks if m.panels), None)


def in_non_blood_section(
    offset: int, marks: list[Heading], *, starts_non_blood: bool = False
) -> bool:
    """Is the text at ``offset`` under a heading that names a non-blood sample?"""
    state = starts_non_blood
    for mark in marks:
        if mark.offset > offset:
            break
        if mark.non_blood is not None:
            state = mark.non_blood
    return state
