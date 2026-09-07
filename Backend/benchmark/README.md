# The gold-standard benchmark

**This directory holds no data, and a manufactured corpus must never be put
here.** A file of plausible-looking labels would be indistinguishable from
clinician-annotated data a few months from now, and every number computed from
it would inherit that. The tests build their fixtures in memory for exactly
this reason.

What lives here is the corpus, once clinicians have produced it, and nothing
else. The apparatus is in `intelligence/benchmark/`.

## Why this is the gate on everything

Every detector in the system reports `NOT_VALIDATED`. That is not modesty. The
rules are taken from published clinical criteria, which makes each one a
*hypothesis* about the reports this system actually receives — photographed
pages from many laboratories, each with its own reference ranges, spellings and
layout. Whether a rule written from a textbook holds there is an empirical
question and nobody has answered it.

Until this corpus exists, the honest description of the system is: it applies
standard criteria correctly and its accuracy on real reports is unknown. Every
finding carries that sentence, and the framework refuses to let a detector
claim otherwise.

## What a clinician is asked

Per report, per applicable code. The annotator first decides which codes the
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

## How the corpus is built

1. **Sample reports the way they actually arrive.** Photographs and scans as
   well as clean PDFs, across the laboratories the system really sees. A corpus
   of tidy machine-generated PDFs measures a system nobody is using.
2. **Two clinicians read every report independently.** One reader's habits
   must not become the ground truth.
3. **A third adjudicates every disagreement**, and records *why* they
   disagreed. Adjudications with no reason are refused.
4. Disagreements that go unadjudicated are **excluded from scoring and
   counted**. Taking a majority would turn measured disagreement into invisible
   agreement, and a code with a high disagreement rate is a code whose
   definition is not sharp enough to score — which is itself a finding.

Start at 200–500 reports. The annotation schema matters more than the count.

## What promotion requires

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
python -m intelligence.benchmark                          # how far off are we
python -m intelligence.benchmark --corpus corpus.json     # validate and report
python -m intelligence.benchmark --corpus corpus.json \
    --outputs system.json --json scores.json              # score it
```

## File format

One JSON document per corpus. See `intelligence/benchmark/corpus.py` for the
loader, which refuses rather than repairs.

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
