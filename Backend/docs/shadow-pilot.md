# The shadow pilot

The document service is wired in as a second reader and the mode is `shadow`.
Nothing it says changes a report. What it produces is a record of where it and
the existing pipeline read the same document differently, kept with the text
that caused each difference.

This document is the procedure for the first batch. It exists because the most
likely way to waste the pilot is not a technical failure - it is reading the
early numbers as if they were a score.

## What the first batch is for

**Failure discovery and corpus construction. Not measurement.**

The sequence is:

```
shadow  ->  collect  ->  adjudicate  ->  discover failure modes
                                              |
                                              v
                                         fix implementation
                                              |
                                              v
                                           repeat
                                              |
                                              v
                                   freeze a benchmark sample
                                              |
                                              v
                                            score
```

Scoring a batch that has already been used to drive fixes measures the fixes,
not the system. The benchmark sample is selected and frozen *after* the failure
modes stop being new, and it is scored once.

## Choosing the pilot set

Chosen for diversity, not volume. The goal is to find failure modes nobody
anticipated, and a set of clean PDFs from one laboratory finds the failure
modes of clean PDFs from one laboratory.

Cover, deliberately:

| Dimension | What to include |
|---|---|
| Capture | clean text PDFs, scanned PDFs, OCR-heavy scans, photographs |
| Source | several laboratories, several report layouts |
| Ranges | reports that print reference intervals, reports that print none, reports whose intervals differ from ours |
| Units | conventional and SI, mg/dL and mmol/L, mEq/L, %, /uL |
| Panel | CBC, glucose and HbA1c, lipids, renal, liver, thyroid, electrolytes |

```
python manage.py shadow_disagreements --coverage
```

prints what has actually been seen and marks the report types that have not.
It also says so explicitly when no OCR capture has been compared yet, because
that is the stratum where the two readers differ most and the easiest one to
skip by accident.

## Running it

```
DOCUMENT_INTELLIGENCE_MODE=shadow
```

The intelligence service must be running and `INTELLIGENCE_SERVICE_TOKEN` must
match on both processes. If it is unreachable, every report still processes
exactly as before and the comparison records "no opinion" - the silence is
visible in the record rather than looking like agreement.

Each report then produces one `ReaderComparison` and a `ReaderDisagreement` row
for every place the readers differed, with the printed label and the line.

## The first review meeting: start with UNKNOWN

```
python manage.py shadow_disagreements --unclassified
```

`UNKNOWN` is where the information is. Everything else in the table is either
a count or a class that followed mechanically from the response.

For each row: open the source document, decide what actually happened, and
record it.

```
python manage.py shadow_disagreements --classify <id> --as PARSER_ERROR \
    --by "dr-mehta" --note "the second reader took the next row's unit"
```

A ruling needs a named reviewer and a written reason - the counts are already
known, and the reason is the only part that says what to change. Each ruling
stores the reviewer, the timestamp and the version of the class definitions in
force when it was made.

`UNKNOWN` is not a class a reviewer may conclude. A row that genuinely cannot
be decided stays `UNKNOWN` with the difficulty written in the note, because
that is a different fact from "nobody has looked yet" only if the note says so.

A disagreement that fits none of the classes is worth more than one that fits:
it is a failure mode nobody anticipated. Record it in the note and raise it.

## Two numbers that will be misread

**A safe abstention is not evidence that the parser is correct.** It
establishes exactly one thing: the second reader declined to make a claim that
could have been unsafe. Whether it *should* have read the line is a separate
question, and the answer is in the document. These rows are pre-classified
`SAFE_ABSTENTION` because the consequence is safe, not because the reading was
right - a reviewer may re-classify one as a parser error.

**Agreement is descriptive, not a quality metric.** A new parser and a broken
legacy reader can agree 99% of the time. The summary prints agreement at the
bottom, labelled, to show how much of the record is disagreement - never as a
result.

**Fabrications cannot be counted here at all.** A fabrication is a value the
report does not support, and neither reader knows what the report says. The
`ONLY_SECOND` rows are where the candidates are; the extraction benchmark is
what settles them.

## The frozen specification is not edited during the pilot

`docs/annotation-spec.md` is versioned and frozen. An edge case that is
inconvenient to label is not a reason to reword a definition mid-collection: a
definition that shifts halfway through leaves early and late annotations
disagreeing about what the label means, and nothing in the data shows it
happened.

If a genuine definition problem is found, it is versioned, and whether the
existing annotations remain compatible is an explicit decision rather than an
assumption. The fingerprint check will refuse to let it happen quietly.

## Building the benchmark from what the pilot found

When the failure modes stop being new, select the extraction benchmark sample
from the adjudicated material - stratified, and deliberately hard:

- OCR noise and split numbers
- mixed and unconventional units
- reference ranges, and reports with none
- censored values (`< 0.01`), duplicate analytes, conflicting values
- ambiguous labels, missing values
- several laboratory formats

Keep every case whose correct answer is **no safe value**. Without them the
benchmark rewards aggressive guessing: a parser that always produces something
scores well on a corpus made only of lines that have an answer.

The headline stays **zero fabricated clinical values**, with extraction
completeness measured separately and never netted against it.

The clinical reasoning benchmark comes after that, scored against the
annotators' structured evidence, so extraction failures cannot contaminate it.

## Turning anything on

`off` -> `shadow` -> `advisory`, and the step to `advisory` is justified by
adjudicated disagreements showing the second reader holds the right reports -
never by an agreement rate looking high. Until then the production mode does
not change.

See also: [`operations.md`](operations.md) for the mode table and the command
reference, [`benchmark.md`](benchmark.md) for the two benchmarks and
[`annotation-spec.md`](annotation-spec.md) for what every label means.
