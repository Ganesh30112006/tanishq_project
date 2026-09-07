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
| Validation | `validation/` | `OBSERVED` / `NEEDS_REVIEW` / `REJECTED`. REJECTED is only for implausible values. Reference status (ABOVE/BELOW/WITHIN/UNKNOWN) is computed here; naming a clinical finding is not. A printed flag that disagrees with the computed status forces NEEDS_REVIEW. |
| Provenance | `provenance/` | Per value: source SHA-256, page, section, char span, exact source line, text source (embedded layer or named OCR provider), per-stage confidences. |

`pipeline.process_document()` runs the whole chain and returns a
`DocumentResult` with the disposition, the validated values with provenance, a
schema completeness roll-up, and typed `Issue`s.

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
