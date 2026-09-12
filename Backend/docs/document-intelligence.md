# Document intelligence

The gap this closes: a photographed or scanned report currently produces
nothing. The risk in closing it: a bad read that produces *something* - a
half-recognised number, a wrong unit, a value with no reference range -
presented as though it were extracted cleanly.

So the module is built as a deterministic library, with a language model kept
out entirely until every deterministic stage works. It lives at
`intelligence/document/`, has no database access, makes no authorization
decision, imports nothing Django, and is reached only over HTTP.

## The pipeline

```
FILE (bytes, base64 from Django)
  │
  ▼
file validation ─────────────► REJECTED_FILE   (not a report type we accept)
  │
  ▼
text-layer extraction (PDF)
  │  usable text layer?
  ├── yes ──────────────┐
  │                     │
  └── no ──► OCR ────────┤   (adapter; engine chosen per deployment)
             │           │
        ENGINE_UNAVAILABLE / NO_TEXT_FOUND / FAILED ──► UNREADABLE
                         │
                         ▼
                  classification ──► NEEDS_REVIEW   (type unclear)
                         │
                         ▼
        section tagging → extraction → normalisation →
        validation → provenance
                         │
                ┌────────┴────────┐
                ▼                 ▼
            EXTRACTED         NEEDS_REVIEW
     (clean values, schema     (values rejected, schema
      COMPLETE)                 not COMPLETE, or a HIGH issue)
```

Every branch ends in a **named `Disposition`**, never an exception for an
ordinary "no" and never an empty string that reads like success.
`intelligence.document.contracts` holds the vocabulary.

## The HTTP boundary

Django is the only caller. It resolves authorization and sends the document
**content** it is entitled to - never a filesystem path or a patient id the
service could use to fetch something itself.

```
POST /v1/documents/process
  { document_id, content_base64, declared_media_type,
    document_type_hint?, requested_operations?, correlation_id }
  -> { document_id, disposition, source_sha256, report_type,
       classification, values[<value + provenance>], completeness,
       issues[{code, severity, detail}], capabilities }

GET /v1/documents/capabilities
  -> which stages can run in this deployment
```

Django side: `IntelligenceClient.process_document(document_id, content, ...)`
returns a `DocumentProcessResult`. Everything on it is advisory -
`apps.reports` decides what becomes an authoritative record and which workflow
opens. `result.needs_human_review` is true unless the disposition is
`EXTRACTED` with no HIGH-severity issue.

The request carries no field that names a location or a patient; a test
asserts the OpenAPI schema has no `path` / `patient_id` / `content_reference`.

## What is built

| Stage | Module | Behaviour |
|---|---|---|
| File validation | `ingestion/file_validation.py` | Type read from the leading bytes. An executable renamed `report.pdf` is rejected with a specific reason. |
| Text layer | `ingestion/text_layer.py` | `pypdf`; a PDF with almost no extractable text is treated as a scan and routed to OCR. A corrupt PDF is a "no", not a crash. |
| OCR | `ocr/` | `OCRProvider` protocol + `LocalTesseractProvider` + registry. Tokens carry `text`, `page`, `BoundingBox` (0..1), `confidence`. No `pytesseract`/engine → `ENGINE_UNAVAILABLE`, no tokens, report held for review. |
| Classification | `classification/keyword.py` | Deterministic weighted keyword vote; all inputs visible in `signals`; winner must beat runner-up 2× or `REVIEW_REQUIRED`. |
| Report schemas | `schemas/` | Per type: fields, required flags, aliases, accepted units, plausibility bounds. Eight panels: CBC, glucose, HbA1c, lipids, renal, liver, thyroid, electrolytes, urinalysis. `assess_completeness()` → COMPLETE / INCOMPLETE / AMBIGUOUS / INVALID / CONFLICTING, same precedence as `apps.reports.schema_engine`; `required_any` covers a report defined by a family of fields rather than one named field. Narrative types have **no** schema. |
| Extraction | `extraction/` | Line-oriented regex → `<label> <value> [unit] [flag] [reference]` with the character span. Skips metadata lines and headings. `parse_reference_range` turns `0 - 6`, `< 200`, `Up to 6` into numbers; marks `Negative` / unparseable as such. |
| Normalisation | `normalization/` | `canonical_analyte()` → known name or `None` (never a guess). `normalize_value()` converts to canonical units from a versioned table whose factors are checked against `apps.common.units` by a test. |
| Validation | `validation/` | A `ValueStatus` - see the table below. Reference status (ABOVE/BELOW/WITHIN/UNKNOWN) is computed here; naming a clinical finding is not. |
| Provenance | `provenance/` | Per value: source SHA-256, page, section, char span, exact source line, text source (embedded layer or named OCR provider), per-stage confidences. |

`pipeline.process_document()` runs the whole chain and returns a
`DocumentResult` with the disposition, the validated values with provenance, a
schema completeness roll-up, and typed `Issue`s.

## Which kind of "no" a value gets

`ValueStatus` values are different *kinds* of answer, not severity levels.
Exactly one of them persists a clinical value, and the others each say why they
do not — which is what makes the no-fabrication guarantee **observable** rather
than merely intended. The vocabulary is kept aligned with
`apps.common.enums.ClinicalDataState` where the two overlap.

| Status | Means | Persists? |
|---|---|---|
| `OBSERVED` | analyte, value and unit all established; plausible; interpretation settled | **yes** |
| `AMBIGUOUS` | the parser could not establish *what was measured* — unrecognised test name, no unit, a unit with no rule, a result given as `< 0.01`, two numbers where one was expected | no |
| `CONFLICTING` | the same analyte appears twice on the document with different values. Neither is chosen | no |
| `INVALID` | outside the analyte's plausibility bounds. A read error, not a sick patient | no |
| `UNREADABLE` | OCR returned this text below the confidence floor, so the characters cannot be vouched for | no |
| `NEEDS_REVIEW` | there *is* a fact and it is plausible, but its interpretation is unresolved — a printed H/L flag disagreeing with the computed status, an unparseable range | no |
| `NOT_FOUND` | only ever the answer to `result.outcome_for(analyte)`. A value that was not found was not extracted | n/a |

Precedence, worst first, matches `apps.reports.schema_engine`:
`CONFLICTING > UNREADABLE > INVALID > AMBIGUOUS > NEEDS_REVIEW > OBSERVED`.

The distinction that earns its keep is **`AMBIGUOUS` against `NEEDS_REVIEW`**.
The first says there is no fact here; the second says there is one and a person
should confirm what it means. Collapsing them would make a line nobody could
read look exactly like one that was read perfectly, and they need completely
different things from a human.

Each refused value also carries a short machine-readable `reason`
(`more_than_one_number_on_the_line`, `result_is_a_bound_not_a_number`,
`unit_not_convertible_for_analyte`, `ocr_below_confidence_floor`, …) so Django
can route without parsing prose, and `persists_clinical_value` is sent
explicitly on the wire rather than left for the caller to re-derive.

## Quantities that share a name but are not the same measurement

The expensive mistakes in this layer are not failures to read a number. They
are successes at reading it into the wrong slot, where it lands beside a real
reference range and looks right. The tables refuse each of these by
construction, and `tests/document/test_analyte_coverage.py` holds them:

| Pair | Why they are separate |
|---|---|
| urea / BUN | urea weighs the whole molecule, BUN only its nitrogen. The same mg/dL number is a different amount of urea, by ~2.14x, so the *label* picks the factor |
| mEq/L calcium / mEq/L sodium | calcium is divalent. A global "mEq/L means mmol/L" alias would double every calcium result |
| differential % / absolute count | a raised lymphocyte percentage with a low white count is a *normal* lymphocyte count. No rule converts one into the other |
| total / ionised calcium | the ionised interval is much narrower; reading one against the other calls a normal result low |
| RDW-CV / RDW-SD | a percentage and a width in femtolitres |
| eGFR / creatinine clearance | one is normalised to body surface area, the other is not. A bare `mL/min` unit is deliberately unrecognised |
| fasting / random glucose | different numbers apply. An *unqualified* glucose has no fallback interval at all - it cannot be read against either, so it is read against neither |

Labels in the second column of that table resolve to `None` rather than to the
nearest field, which routes them to review.

## What comes after extraction

Validated values feed the finding and disease framework - see
[finding-detection.md](finding-detection.md). Levels 2 and 3 are built; level 4
is the governed risk model in Django and stays frozen. Everything the pipeline
produces is a `SINGLE_REPORT` evidence set, so no finding drawn from it may be
read as a persistent or chronic condition; the framework enforces that rather
than relying on the reader.

Still missing: the annotated corpus for the gold-standard benchmark, and the
LLM module. The benchmark *apparatus* is built - see [benchmark.md](benchmark.md)
- but clinicians produce the labels and they must not be manufactured, so every
detector is `NOT_VALIDATED` until that work happens. The LLM, when it lands, receives the validated structured
findings this pipeline produces, never a raw document.

## The OCR adapter

```python
from intelligence.document.ocr import default_provider, register_provider
from intelligence.document.ocr.provider import OcrRequest

provider = default_provider()                 # deployment default, never None
result = provider.run(OcrRequest(image_bytes=data, media_type=media_type))
register_provider("my-cloud-ocr", MyCloudOCRProvider)   # deployment wiring
```

Enabling local OCR needs the Python package **and** the system engine - see
[operations.md](operations.md#document-intelligence-runtime-requirements) for
the capability matrix. Without the engine every path still works; scanned
reports route to review.

## How Django uses it: a second reader

The existing `apps.reports` pipeline works. Clinicians act on what it produces
today, and the benchmark corpora that would justify replacing its extraction do
not exist — so "the new parser is better" is a belief, not a finding. The
integration is built so that the belief does not have to be true for the change
to be safe.

The service is a **second reader whose opinion may only make the outcome more
conservative**:

> a report the existing pipeline would FINALIZE may be held for review
> a report the existing pipeline would hold may **never** be finalized

`settings.DOCUMENT_INTELLIGENCE["MODE"]`:

| | |
|---|---|
| `off` | **the default.** Not called. Behaviour is unchanged until someone deliberately turns it on, and an unrecognised value falls back here so a typo cannot enable a clinical path |
| `shadow` | (current setting) called; what it said goes into the audit trail, and every disagreement with the existing reader is kept in `reports_reader_disagreement` with the line that caused it. The outcome is untouched. Run this first — it produces the comparison that would justify going further |
| `advisory` | called; may hold a report that would otherwise finalize |

**Nothing it returns is ever persisted as a clinical value**, in any mode. It
creates no `ReportTest`, touches no `Provenance`, and changes no number. It can
say "a person should look at this", with a reason, and nothing else.

**Availability is never a clinical dependency.** Every failure — service down,
timeout, malformed response, missing credential — produces "no opinion", is
recorded so the silence is visible, and the pipeline continues exactly as it
would have. A report must not become unprocessable because an optional service
is unreachable.

`tests/integration/test_second_reader.py` checks the invariant across every
combination of mode and service answer, including answers the code has never
seen: an unrecognised disposition raises no concern, because the holding set is
named rather than inferred.

## Boundaries

* **The cardiovascular pathway must never import this package.**
  `tests/regression/test_cvd_isolation.py` enforces it with an AST import-graph
  check over `apps/risk`, `intelligence/ml_service` and
  `apps/common/intelligence.py`. A crash, hang or nonsense return from document
  intelligence cannot reach a risk assessment because none of that code is on
  the CVD engine's call graph.
* **Django ↔ intelligence is HTTP only.** `apps.reports` must not import
  `intelligence.document`; it calls the endpoint. Django owns auth,
  authorization, patient scope, workflow, the authoritative records and audit.
  An AST import check in `tests/integration/test_second_reader.py` walks every
  file under `apps/reports` and fails on any `intelligence.*` import — putting
  the parser in the web process would quietly delete the boundary rather than
  break anything visible.
* **OCR output is not clinical truth.** It carries confidence and provenance;
  a later stage decides whether to trust it.

## Tests

`tests/document/` - ingestion, the OCR adapter (every no-engine path),
classification and its abstentions, schema completeness precedence, extraction
/ reference parsing / normalisation / validation / provenance, the wired
pipeline, and the HTTP endpoint. `tests/integration/test_document_client.py` -
the Django client, including the scoped-payload assertion.
`tests/regression/test_ocr_never_fabricates.py` pins the safe behaviour of the
existing `apps.reports` pipeline so it is preserved once the two are wired
together.

**`tests/document/adversarial/`** is the near-miss corpus, and it is
deliberately *not* the clinical gold-standard benchmark. Nothing in it is
clinician-annotated and nothing in it says whether a value is clinically
meaningful. It answers one question — can the parser be made to manufacture a
structured clinical fact out of text that does not support one? — over the
shapes real reports and real OCR produce: the same test spelled six ways, two
quantities sharing a printed name, a number OCR split in half, a result the
assay declined to measure, one analyte printed twice with two different
numbers. Being unable to read a report is safe; reading it wrongly with
confidence is not, and is invisible downstream.

It found the `HbA1c 6.2 %` bug by exercising the implementation rather than by
reading the rules, after that bug had been live for three commits.
