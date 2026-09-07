# Finding and disease detection

The framework that stands between a laboratory number and anything resembling a
clinical conclusion. It exists so that adding the fifteenth body system is the
same amount of work as the first, and so that the shortcut nobody should take
is not available to take.

## Four levels, and nothing skips one

| Level | Kind | Example | Where |
|---|---|---|---|
| 1 | Laboratory finding | `Hb 9.8 g/dL -> BELOW_REFERENCE_RANGE` | `intelligence/document/validation` |
| 2 | Clinical abnormality | `ANEMIA_PATTERN` | `intelligence/findings/` |
| 3 | Condition likelihood | `POSSIBLE_IRON_DEFICIENCY_ANEMIA` | `intelligence/disease/` |
| 4 | Disease / risk model | the governed CVD model | `apps/risk` + `intelligence/ml_service` |

The levels are enforced by `EvidenceContract.__post_init__`, not by convention:

* **A level-2 code must be named as a pattern.** `ANEMIA` is refused;
  `ANEMIA_PATTERN` is accepted. The name is what a clinician reads first.
* **A level-3 code must be hedged and must need a combination.** The code has
  to start with `POSSIBLE_` / `SUSPECTED_`, and a contract with fewer than two
  pieces of evidence will not construct. This is the rule that makes
  "Hb 9.8 -> iron deficiency" impossible to write.
* **Levels 3 and 4 always require human review.** `human_review_required=False`
  is refused.
* **A level-2 pattern reads one report.** Whether an abnormality persists is a
  level-3 question, so a level-2 contract may not declare any temporality
  other than `SINGLE_REPORT`.
* **A level-4 detector must already be `CLINICALLY_APPROVED`.** A risk model
  cannot be created by writing a Python class; it needs a governed
  `ModelVersion` in Django with a named approver and an evidence dossier. The
  cardiovascular model is the only one, and it stays frozen and independent.

## Every detector says what stands behind it

`DetectorValidation` is `NOT_VALIDATED`, `BENCHMARKED` or
`CLINICALLY_APPROVED`, and an unvalidated detector must state what has not been
measured — the contract refuses a blank note. Today **every detector in the
registry is `NOT_VALIDATED`**, and a test asserts it stays that way until a
clinician-annotated gold-standard set exists. The rules are copied from
standard clinical criteria; their precision and recall *on the reports this
system actually receives* is unknown, and every finding carries that sentence.

That is the same discipline as the model evidence dossier: a rule from a
textbook is a hypothesis about this system's data until somebody measures it
here.

## A detector may not outrun the timeline it was given

"Abnormal now" and "abnormal for three months" are different clinical
statements, and only the second one is a chronic disease. An eGFR of 55 on one
report is a low eGFR; chronic kidney disease needs the same abnormality to
persist for at least ninety days.

Nothing in the output distinguishes the two. A finding that says "possible
chronic kidney disease" reads identically whether ninety days of history stood
behind it or nobody checked. So the check does not live in a detector's good
intentions:

| | |
|---|---|
| `SINGLE_REPORT` | one report, one moment. Every level-2 pattern |
| `REPEATED_MEASUREMENT` | the same analyte measured more than once |
| `HISTORICAL` | repeated measurement plus a minimum elapsed time |
| `CROSS_REPORT` | different analytes from different reports, correlated |

A detector declares what it needs (`EvidenceContract.temporality`, plus a
`temporality_requirement` sentence naming exactly what). The `EvidenceSet`
declares what it actually holds (`available_temporality`). The engine
downgrades any assertion the set has no timeline for to `INSUFFICIENT`,
putting the requirement into `evidence_missing` so the result says what was
needed.

Today the document pipeline produces `SINGLE_REPORT` sets only. Building the
multi-report evidence assembly is a later phase; until it exists, a detector
needing history correctly returns "not enough evidence" on every call and
names the repeat it wanted.

## Confidence means "how much evidence", not "how sure"

| | |
|---|---|
| `SUPPORTED` | every required piece of evidence present and pointing one way |
| `PROVISIONAL` | present but weakened — an assumed reference range, an unknown sex, a decision threshold rather than a reference interval |
| `INSUFFICIENT` | not enough to say. The finding names what is missing and asserts nothing |

An `INSUFFICIENT` finding is never built upon by a higher level. "I cannot
tell" is a statement about the report, not a fact about the patient.

And a detector whose analyte is simply absent returns **nothing at all** —
silence and "I cannot tell" are different answers, and a lipid report should
not carry a notice about missing haemoglobin.

## The laboratory's own reference range wins

Always. It was set by the lab that ran the assay, on its instrument, for its
population. `intelligence/knowledge/reference_ranges.py` is a fallback for
reports that print none, and any finding that used it says so in its caveats.

The table separates two kinds of number that are routinely blurred:

* a **reference interval** — the central range of a healthy population;
  outside it means *unusual*, a laboratory statement;
* a **decision threshold** — a guideline number where acting changes outcomes
  (LDL, HbA1c); outside it means *worth acting on*, a clinical statement.

A finding built on a decision threshold can never exceed `PROVISIONAL`, and it
says that the number is a treatment target rather than an abnormality boundary.

## The knowledge dictionary decides what may be said

`intelligence/knowledge/findings/` holds, for each finding: definition, a
plain-English explanation in simple Indian English, common associations,
cautionary notes, and `must_not_say`. A detector may not compose its own
explanation — `build_finding` raises if the code has no knowledge entry.

`must_not_say` is the part that does real work. Eosinophilia is associated with
parasitic infection, so a model asked to explain it will reach for that, and a
patient reading "you may have a parasite" from a routine blood count has been
harmed by a system trying to be helpful. Each entry states its bound:

```
EOSINOPHILIA_PATTERN.must_not_say:
  Do not tell a patient they have a parasitic infection...
  Do not name a blood cancer.
  Do not advise stopping any medicine.
```

When a language model is added it communicates this dictionary. It does not
decide any of it and may not introduce an association the dictionary omits.

## Standing prohibitions, checked rather than remembered

* **No tumour marker may map to a cancer.** `CEA high -> cancer`,
  `CA-125 -> ovarian cancer`, `PSA -> prostate cancer` are the exact shapes
  banned; a test fails if any registered detector reads one of those markers.
* **No abnormal blood count may become "infection detected."**
  `LEUKOCYTOSIS_PATTERN` says a white count is raised and explicitly must not
  say an infection was found.
* Neurological, respiratory, ophthalmic, dermatological and ENT conditions
  generally cannot be inferred from routine blood work and have no detectors.

## Everything is traceable

A finding carries its detector `code:version`, the reference-range table
version, the knowledge version, and for each piece of evidence: the analyte,
value, unit, which reference range was used and from where, the page, the
section, the character span and the exact source line — straight through to the
document provenance. It also carries what was **missing**.

## What is built

Level 2, `intelligence/findings/`, 34 detectors across five body systems:

| Module | Patterns |
|---|---|
| `hematology` | anaemia, polycythaemia, leukocytosis, leukopenia, thrombocytopenia, thrombocytosis, eosinophilia, microcytosis, macrocytosis, raised RDW |
| `metabolic` | hyperglycaemia, raised HbA1c, dyslipidaemia (panel-level, `required_evidence_mode="any"`) |
| `renal` | raised creatinine, reduced eGFR, raised urea, albuminuria |
| `hepatic` | raised ALT, AST, ALP, GGT, bilirubin; low albumin |
| `thyroid` | raised TSH, low TSH, low free T4, high free T4 |
| `electrolytes` | low/high sodium, low/high potassium, low/high calcium, low bicarbonate |

Three shapes recur, and each is a decision rather than an oversight:

* **One enzyme, one finding.** The liver panel is six separate findings, not
  one "deranged liver function". Which enzymes rose *together* is the whole of
  the information a liver panel carries, and collapsing them discards it.
  Reading the combination is a level-3 question.
* **The artefact travels with the result.** Electrolytes are the one place a
  number can be an emergency and also the place a wrong number is commonest,
  so each contract names what most often fakes it - haemolysis for potassium,
  a low albumin for calcium, a tube left standing for bicarbonate. No detector
  estimates urgency; that is a judgement about a patient, not a comparison
  against a range.
* **Represented is not the same as detected.** Several analytes are read,
  normalised and compared but have no detector on purpose - the percentage
  differential (neutropenia needs an absolute count, which the unit rules
  refuse to derive from a percentage), the red cell indices, and the values
  that only mean something inside a combination. The list lives in
  `tests/findings/test_level2_expansion.py` and the test fails if a detector
  appears for one without the entry being removed.

Level 3, `intelligence/disease/hematology/`: `POSSIBLE_IRON_DEFICIENCY_ANEMIA`,
which is there mostly to prove the boundary holds. On most reports it returns
`INSUFFICIENT` naming MCV and ferritin as missing — which is the honest answer,
because thalassaemia trait gives the same blood count and iron given for the
wrong reason is harmful.

`intelligence/disease/` is otherwise deliberately empty. The categories the
framework must eventually express are listed in its docstring.

## Using it

```python
from intelligence.findings import build_evidence, detect

evidence = build_evidence(result.values, sex="female")   # document pipeline output
report = detect(evidence)
```

Over HTTP it comes back on the same `POST /v1/documents/process` call, in a
`findings` block, when `detect_findings` is among the requested operations.
`patient_sex` and `patient_age_years` may be supplied as clinical *attributes* —
they are not identifiers and the service cannot resolve them to a person.

## Tests

`tests/findings/test_framework_contracts.py` — the structural guards: naming,
the combination rule, the review rule, the level-4 gate, the validation gate,
the tumour-marker prohibition, knowledge coverage.
`tests/findings/test_temporality.py` — the timeline gate, including the engine
backstop that downgrades a conclusion the evidence set has no history for.
`tests/findings/test_level2_expansion.py` — the renal, hepatic, thyroid and
electrolyte patterns, and the deliberate-omission list.
`tests/findings/test_detectors.py` — evidence assembly, reference precedence,
level-2 behaviour and the level-3 boundary.
`tests/document/test_http_endpoint.py` — the findings block over the wire.
