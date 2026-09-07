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

## The apparatus

```
intelligence/benchmark/
  schema.py     what a clinician is asked, and the shape of the answer
  corpus.py     reading an annotated set off disk, strictly
  labels.py     several clinicians' answers -> the one label a score needs
  scoring.py    precision, recall, F1, abstention, with real intervals
  promotion.py  when a detector may stop calling itself NOT_VALIDATED
```

`benchmark/README.md` is the guide clinicians and whoever organises the
annotation work from. It holds no data, and a manufactured corpus must never be
put there — `tests/benchmark/test_no_manufactured_corpus.py` fails if anything
in the tree starts to look like one.

## Four things counted, kept apart

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
python -m intelligence.benchmark                       # how far off are we
python -m intelligence.benchmark --corpus corpus.json  # validate and report
python -m intelligence.benchmark --corpus corpus.json \
    --outputs system.json --json scores.json           # score it
```

Today:

```
corpus            none
reports           0 of 200 required
promotable        0

Blocking:
  - No annotated corpus exists. 200 reports, each read by at least 2
    clinicians, are needed before any detector can be measured.
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
