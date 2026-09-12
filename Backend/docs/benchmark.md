# The gold-standard benchmark

The gate on every accuracy claim this system could make, built before there is
any data to put through it.

## Why every detector says NOT_VALIDATED

Forty detectors ship, and every one of them reports `NOT_VALIDATED`. That is
not modesty and it is not a placeholder. The rules are taken from published
clinical criteria, which makes each one a **hypothesis** about the reports this
system actually receives — photographed pages from many different laboratories,
each with its own reference ranges, spellings and layout. Whether a rule
written from a textbook holds *there* is an empirical question, and nobody has
answered it.

The Phase 4 work makes the point concretely. Expanding the analyte tables
surfaced an extraction bug in which `HbA1c 6.2 %` was read as the analyte "HbA"
with the value 1 and the unit "c" — a silent fabrication, live in the code,
that no amount of reading the rules would have revealed. An annotated corpus
would have caught it on the first report.

So: until this corpus exists, the honest description of the system is that it
applies standard criteria correctly and its accuracy on real reports is
unknown. Every finding carries that sentence, and the framework refuses to let
a detector claim otherwise.

## Two benchmarks, not one

"Does the system get this right?" is two questions, and answering them together
answers neither:

```
text or image        ->  structured evidence      the extraction benchmark
structured evidence  ->  finding or condition     the reasoning benchmark
```

A detector can reason flawlessly on a misread haemoglobin. Extraction can be
perfect and feed a rule that draws an unsafe conclusion. Scored together those
two failures are indistinguishable, and the number they produce tells nobody
which layer to fix — so they are separate corpora, separate scores and
separate gates.

The reasoning benchmark is scored against the **annotators'** structured
evidence, not the parser's. A detector is not penalised for a value the parser
misread, and is not credited when good extraction masks an unsafe rule.

The split is also cheaper. Transcribing a printed report accurately is a
different skill from judging whether a result is clinically meaningful, so the
extraction corpus does not need clinician time — which matters, because it is
the larger of the two.

```
intelligence/benchmark/
  extraction/     schema, loader, scoring for the reading layer
  reasoning/      schema, loader, scoring for the clinical layer
  adjudication.py several annotators -> the one label a score needs (shared)
  statistics.py   proportions with intervals that behave at the extremes
  promotion.py    both gates, written before there was data to run
```

`benchmark/README.md` is the guide clinicians and whoever organises the
annotation work from. It holds no data, and **neither** corpus may ever be
manufactured — `tests/benchmark/test_no_manufactured_corpus.py` fails if
anything in the tree starts to look like one.

The adversarial suite at `tests/document/adversarial/` is a different thing
again, and not a substitute for either. It asks whether the parser can be made
to fabricate a fact out of text that does not support one — an invariant,
checkable with no annotation at all. It says nothing about whether the system
reads reports *well*.

## The extraction benchmark

An annotator transcribes each result line exactly as printed: analyte, value,
unit, reference range, printed flag, section, and the document type. Four
things are counted.

**Detection** — which lines the parser found: precision, recall, F1.

**Transcription** — of the lines it found, how many of the value, unit,
reference range, flag and section it got right, scored **per attribute**. A
parser that reads every number right and every unit wrong is a different
problem from one that does the reverse, and one accuracy figure hides both.

**Fabrication** — the headline, and not precision. A value the parser
*persisted* that the report does not print, or a value persisted for a line the
annotators marked as yielding nothing. A missed result is a gap a person can
see; a wrong result is one nobody can. They are never added together.

**Refusal** — lines that must yield nothing (page numbers, accession numbers,
censored results) and whether the parser also yielded nothing. Most of a report
is not a result, and a corpus recording only the results cannot measure whether
the parser invents any, so a corpus without them is reported as incomplete.

A value the parser produced but marked as **not persistable** is not a
fabrication. Refusing out loud is what the status ladder exists to produce, and
counting it as an error would push the system towards confident guesses.

`should_not_be_extracted` is the field that does the most work, and it must say
*why* — that reason is what the parser is being asked to reproduce.

## The reasoning benchmark: four things counted, kept apart

**Agreement.** True and false positives and negatives, and precision, recall
and F1 from them. Every proportion carries a Wilson score interval, because a
recall of 1.0 from four positive cases is not a recall of 1.0 and reporting it
as one is how a detector gets trusted on nothing.

**Abstention.** An abstention on a report the clinician called PRESENT is a
miss and is counted as one — a system that abstained on everything scores a
recall of zero, which is correct, because otherwise "we do not know" becomes a
way of scoring well. But abstaining and asserting absence are different
failures and the second is more dangerous, so `missed_by_abstaining` is
reported alongside.

**Appropriate abstention.** Where the *clinician* answered
`CANNOT_DETERMINE`, the report genuinely did not settle it. Those items leave
precision and recall entirely and are counted on their own, with how often the
system also abstained. That number is the one that says whether the system
knows what it does not know.

**Out-of-scope assertions.** A detector firing where no annotator scoped the
code. Never a scoring category — a defect report. Either the annotation is
incomplete or the detector is firing where it has no business, and both need a
person. Any at all block promotion.

## The definitions are frozen before collection starts

Two annotators can answer the same questions and produce incompatible data,
because they did not mean the same thing by AMBIGUOUS. That failure never looks
like a data error - it looks like annotator disagreement, or like a detector
that does worse on the half of the corpus labelled later.

So the meanings are fixed first, in `intelligence/benchmark/spec.py`, and
`docs/annotation-spec.md` - the handbook every annotator reads - is generated
from them. Three mechanisms keep them fixed:

| Mechanism | What it stops |
|---|---|
| `FROZEN_FINGERPRINT`, checked by a test | a definition changing without anyone deciding to change it |
| the handbook is generated, never edited | the document annotators read drifting from the rules the scorer applies |
| `spec_version` on every annotation, refused when it differs | labels that mean different things being pooled into one score |

A change is not forbidden, it is loud: the fingerprint fails, and if the
wording could alter a label already given, `ANNOTATION_SPEC_VERSION` is bumped
and the affected items are re-annotated. Reports labelled under the old version
are not scored with the new ones.

The specification also covers every answer either benchmark can record - not
only the terms above but `PRESENT`, `ABSENT`, `SUPPORTED`, `NOT_SUPPORTED`,
`SUFFICIENT`, `INSUFFICIENT` and `CANNOT_DETERMINE`. A test cross-checks the
enums against it, so a new answer option cannot reach an annotator undefined.

## Resolving several readers into one label

| | |
|---|---|
| annotators agree | that is the label |
| they differ, a third adjudicated | the ruling is the label |
| they differ, nobody adjudicated | **there is no label** — excluded and counted |

The third row is the one worth defending. A majority vote would produce a
label, and it would turn a case two clinicians could not agree on into a case
the detector is measured against as though it were settled. Disagreement
between readers is itself a measurement — a code with a high disagreement rate
is a code whose definition is not sharp enough to score — and it is destroyed
by being resolved automatically. The rate is reported and it is one of the
promotion requirements.

## Two gates

**Extraction readiness** gates whether the parser has been measured well enough
for anything downstream to be measured at all — a reasoning score computed
over a corpus whose extraction was never checked is a number about two layers
at once.

| Requirement | Value |
|---|---|
| `corpus_size` | 200 documents |
| `fields_measured` | 500 transcribed result lines |
| `refusable_lines` | 100 lines that must yield nothing |
| `double_read` | every document, 2 annotators |
| `disagreements_adjudicated` | at most 5% unresolved |
| `no_fabrications` | **zero** |

That last one is the only correctness bar in either benchmark. A parser that
persists a number the report does not print is not a less-accurate parser; it
is one whose output nobody can act on, and no amount of corpus size makes that
measurable-and-fine.

**Detector promotion** gates one detector moving from `NOT_VALIDATED` to
`BENCHMARKED`.

## Promotion: measured, not good

`BENCHMARKED` means the detector has been **measured**. It does not mean it
performed well. A detector whose measured precision is poor should be
`BENCHMARKED` — measured, and known to be poor — not left at `NOT_VALIDATED` as
though nobody had looked, because that would hide the measurement, which is the
opposite of what the measurement is for.

So none of the gates is a performance floor. They ask whether the measurement
is large enough and clean enough to mean anything:

| Requirement | Value |
|---|---|
| `corpus_size` | 200 reports |
| `positive_events` | 30 per code — recall is estimated from these and nothing else |
| `negative_events` | 30 per code — precision needs a chance to be wrong |
| `double_read` | every report, 2 clinicians |
| `disagreements_adjudicated` | ≤ 5% unresolved |
| `recall_interval` | 95% CI on recall spans ≤ 0.35 |
| `no_out_of_scope_assertions` | zero |

Whether a benchmarked detector should be *used* is a separate question with a
separate answer: `CLINICALLY_APPROVED`, which needs a named person and the
Django governance lifecycle, exactly as the cardiovascular risk model does.

**Promotion is never automatic.** The tooling produces a recommendation.
Changing a `validation_status` is an edit to a contract in code, made by a
person who has read the numbers — the same discipline as the model evidence
dossier, where approval requires a human to acknowledge each open question.

## Running it

```
python -m intelligence.benchmark
python -m intelligence.benchmark --write-handbook
python -m intelligence.benchmark --extraction-corpus extraction.json \
    --extraction-outputs parsed.json
python -m intelligence.benchmark --reasoning-corpus reports.json \
    --outputs system.json --json scores.json
```

Today, and reported layer by layer rather than as one number:

```
1. Extraction   text or image -> structured evidence
corpus            none
documents         0 of 200 required
ready             no
  - No extraction corpus exists. 200 documents, each transcribed by at
    least 2 annotators, are needed before the parser can be measured.

2. Clinical reasoning   structured evidence -> finding or condition
corpus            none
reports           0 of 200 required
promotable        0
  - No clinician-annotated corpus exists. 200 reports, each read by at
    least 2 clinicians, are needed before any detector can be measured.
```

That is the intended output. The apparatus exists, the data does not, and every
detector says so in every result it emits.

## Relationship to the model evidence dossier

The same discipline applied one level down. `docs/model-evidence.md` makes a
*model* state what is still unknown about it and forces an approver to
acknowledge each gap. This does the same for the *rules*: it turns "we believe
these criteria work" into a question with a defined answer, defines what would
count as an answer before the answer is known, and refuses to let a
reassuring summary outlive the measurement.
