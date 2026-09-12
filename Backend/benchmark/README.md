# The gold-standard benchmarks

There are **two**, and they are annotated separately:

| | Question | Who annotates |
|---|---|---|
| **Extraction** | text or image -> structured evidence. Did we read it correctly? | anyone who can read a laboratory report accurately |
| **Reasoning** | structured evidence -> finding or condition. Did we conclude safely? | clinicians |

A detector can reason flawlessly on a misread haemoglobin, and perfect
extraction can feed an unsafe rule. Scored together those failures are
indistinguishable. Keeping them apart is also what makes the larger corpus
affordable: transcribing a printed report is not a clinical judgement, so the
extraction corpus does not need clinician time.

The reasoning benchmark is scored against the **annotators'** structured
evidence rather than the parser's output, so a reasoning score measures
reasoning.

**This directory holds no data, and neither corpus may ever be manufactured.**
A file of plausible-looking labels would be indistinguishable from real
annotation a few months from now, and every number computed from it would
inherit that. The tests build their fixtures in memory for exactly this reason.

What lives here are the two corpora, once annotators have produced them, and
nothing else. The apparatus is in `intelligence/benchmark/`.

## What an extraction annotator is asked

Per document, per printed line. No clinical judgement is involved: the question
is what the page says, not what it means.

| Field | |
|---|---|
| `printed_label` | the test name exactly as printed — this is what the parser sees |
| `analyte` | the canonical name it refers to, or blank if it is not one we model |
| `value`, `unit` | as printed, not converted |
| `reference_text` | the range as printed |
| `printed_flag` | H / L / any marker the report puts beside the result |
| `section` | the heading the line sits under |
| `should_not_be_extracted` | **true for every line that must yield nothing**, with `why_not` |

That last field does the most work. Most of a report is not a result — page
numbers, accession numbers, ages, dates, method notes, a result the assay
declined to measure — and a parser that turns any of those into a clinical
value has fabricated one. Recording them is how that gets measured rather than
assumed; a corpus without them is reported as incomplete, because it can only
measure what the parser reads and never what it invents.

Also recorded per document: the report type, and whether the document is
readable at all.

## Why this is the gate on everything

Every detector in the system reports `NOT_VALIDATED`. That is not modesty. The
rules are taken from published clinical criteria, which makes each one a
*hypothesis* about the reports this system actually receives — photographed
pages from many laboratories, each with its own reference ranges, spellings and
layout. Whether a rule written from a textbook holds there is an empirical
question and nobody has answered it.

Until these corpora exist, the honest description of the system is: it applies
standard criteria correctly and its accuracy on real reports is unknown. Every
finding carries that sentence, and the framework refuses to let a detector
claim otherwise.

## What a clinician is asked

This is the reasoning corpus, and it needs clinicians. Per report, per
applicable code. The annotator first decides which codes the
report could reasonably carry — a lipid panel is not scored for thyroid codes —
and then answers for each of them. Declaring a code applicable and not
answering it is refused at load time, because an unanswered code silently
leaves the denominator and the recall that results is wrong in a direction
nobody can see.

**For a level-2 finding**

| Question | Answers |
|---|---|
| Is the finding present? | `PRESENT` / `ABSENT` / `CANNOT_DETERMINE` |
| Was the evidence sufficient to decide? | `SUFFICIENT` / `INSUFFICIENT` |
| Alternative explanation? | free text |

**For a level-3 condition**

| Question | Answers |
|---|---|
| Do the results support it? | `SUPPORTED` / `NOT_SUPPORTED` / `INSUFFICIENT` |
| Alternative explanation? | free text |

**For the report as a whole**

| Question | Answers |
|---|---|
| Would this need a person to look before anything was acted on? | yes / no |
| Which printed values did you use? | list |
| What did you want that the report did not have? | list |

`CANNOT_DETERMINE` is a real answer, not a gap. The case where the clinician
cannot tell either is exactly the case where the system abstaining is
*correct*, so those items are scored separately rather than dropped — and the
resulting number is the one that says whether the system knows what it does
not know.

The free-text alternative explanation is the most valuable field in the
corpus. It is where the cases the rules get wrong describe themselves: a
haemolysed sample, a patient who had been fasting, a laboratory whose ALP
range is set for adolescents.

## How either corpus is built

The procedure is the same for both; only who annotates differs.

1. **Sample reports the way they actually arrive.** Photographs and scans as
   well as clean PDFs, across the laboratories the system really sees. A corpus
   of tidy machine-generated PDFs measures a system nobody is using.
2. **Two annotators read every document independently.** One reader's habits
   must not become the ground truth.
3. **A third adjudicates every disagreement**, and records *why* they
   disagreed. Adjudications with no reason are refused.
4. Disagreements that go unadjudicated are **excluded from scoring and
   counted**. Taking a majority would turn measured disagreement into invisible
   agreement, and a code with a high disagreement rate is a code whose
   definition is not sharp enough to score — which is itself a finding.

Start at 200–500 reports. The annotation schema matters more than the count.

## What the extraction gate requires

Measured separately, and gating everything downstream: a reasoning score
computed over a corpus whose extraction was never checked is a number about two
layers at once.

| Requirement | Value | Why |
|---|---|---|
| corpus size | 200 documents | |
| result lines | 500 transcribed | below this the detection measurement is too thin |
| refusable lines | 100 | without them the corpus cannot measure whether the parser invents values |
| annotators | 2 per document | one person's transcription must not become the truth |
| unadjudicated disagreements | at most 5% | |
| **fabrications** | **zero** | the only correctness bar in either benchmark |

The last row is not a performance floor. A parser that persists a number the
report does not print is not a less-accurate parser; it is one whose output
nobody can act on, and no corpus size makes that acceptable.

A value the parser produced but marked **not persistable** is not a
fabrication. Refusing out loud is the behaviour the whole status ladder exists
to produce, and counting it as an error would push the system towards confident
guesses.

## What detector promotion requires

`BENCHMARKED` means **measured**, not good. A detector whose measured precision
is poor should be `BENCHMARKED` — measured, and known to be poor — not left at
`NOT_VALIDATED` as though nobody had looked. So none of these gates is a
performance floor; they ask whether the measurement is large enough and clean
enough to mean anything.

| Requirement | Value | Why |
|---|---|---|
| corpus size | 200 reports | a small set is unrepresentative in ways no per-code count reveals |
| positive events | 30 per code | recall is estimated from these and nothing else |
| negative events | 30 per code | precision needs a chance to be wrong |
| annotators | 2 per report | see above |
| unadjudicated disagreements | ≤ 5% | above this the corpus describes the annotators, not the detector |
| width of the 95% CI on recall | ≤ 0.35 | wider than this does not support the word "measured" |
| out-of-scope assertions | 0 | a detector firing where no annotator scoped the code means the measurement did not cover what the detector does |

Whether a benchmarked detector should be *used* is a separate question with a
separate answer: `CLINICALLY_APPROVED`, which needs a named person and the
Django governance lifecycle, exactly as a risk model does.

**Promotion is never automatic.** The tooling produces a recommendation.
Changing a detector's `validation_status` is an edit to its contract in code,
made by a person who has read the numbers.

## Running it

```
python -m intelligence.benchmark
python -m intelligence.benchmark --extraction-corpus extraction.json \
    --extraction-outputs parsed.json
python -m intelligence.benchmark --reasoning-corpus reports.json \
    --outputs system.json --json scores.json
```

The readiness output is always reported layer by layer, never as one number: a
caller has to be able to see which layer is the obstacle, because the two are
fixed by completely different work — one needs parser changes, the other needs
clinician time.

## File format

One JSON document per corpus, and the two have separate schemas. See
`intelligence/benchmark/reasoning/corpus.py` and
`intelligence/benchmark/extraction/corpus.py` for the loaders, which refuse
rather than repair.

An extraction corpus looks like this — note that the page-number line
is as important as the result:

```json
{
  "corpus_id": "clinic-a-extraction-2026-q1",
  "schema_version": "benchmark-extraction-1",
  "items": [
    {
      "document_id": "d-0001",
      "source_sha256": "<hash of the document the annotators read>",
      "capture": "phone photograph",
      "annotations": [
        {
          "document_id": "d-0001",
          "annotator_id": "annotator-1",
          "annotated_on": "2026-02-11",
          "document_type": "CBC",
          "readable": true,
          "fields": [
            {
              "analyte": "hemoglobin",
              "printed_label": "Hemoglobin",
              "value": 13.4,
              "unit": "g/dL",
              "reference_text": "13.0 - 17.0",
              "section": "COMPLETE BLOOD COUNT"
            },
            {
              "analyte": "",
              "printed_label": "Page 1 of 3",
              "should_not_be_extracted": true,
              "why_not": "page furniture, not a result"
            }
          ]
        }
      ]
    }
  ]
}
```

And a reasoning corpus:

```json
{
  "corpus_id": "clinic-a-2026-q1",
  "schema_version": "benchmark-annotation-1",
  "items": [
    {
      "report_id": "r-0001",
      "report_type": "CBC",
      "source_sha256": "<hash of the document the annotators read>",
      "annotations": [
        {
          "report_id": "r-0001",
          "report_type": "CBC",
          "annotator_id": "clinician-1",
          "annotated_on": "2026-02-11",
          "applicable_finding_codes": ["ANEMIA_PATTERN", "MICROCYTOSIS_PATTERN"],
          "applicable_condition_codes": ["POSSIBLE_IRON_DEFICIENCY_ANEMIA"],
          "findings": [
            {
              "code": "ANEMIA_PATTERN",
              "determination": "PRESENT",
              "evidence_sufficient": "SUFFICIENT"
            },
            {
              "code": "MICROCYTOSIS_PATTERN",
              "determination": "CANNOT_DETERMINE",
              "evidence_sufficient": "INSUFFICIENT",
              "note": "MCV not printed on this report"
            }
          ],
          "conditions": [
            {
              "code": "POSSIBLE_IRON_DEFICIENCY_ANEMIA",
              "support": "INSUFFICIENT",
              "alternative_explanation": "no ferritin; thalassaemia trait not excluded"
            }
          ],
          "human_review_required": true,
          "supporting_evidence": ["Hemoglobin 9.8 g/dL (13.0 - 17.0)"],
          "missing_evidence": ["MCV", "ferritin"]
        }
      ],
      "adjudication": null
    }
  ]
}
```
