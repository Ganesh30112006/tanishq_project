# Document intelligence

The gap this closes: a photographed or scanned report currently produces
nothing. The risk in closing it: a bad read that produces *something* - a
half-recognised number, a wrong unit, a value with no reference range -
presented as though it were extracted cleanly.

So the module is built as a deterministic library first, with a language model
kept out entirely until the deterministic stages work. It lives at
`intelligence/document/` and has no database access, makes no authorization
decision, and imports nothing Django.

## The pipeline

```
FILE (bytes)
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
             ▼           ▼
        ENGINE_UNAVAILABLE / NO_TEXT_FOUND / FAILED ──► UNREADABLE
                         │
                         ▼
                  classification ──► NEEDS_CLASSIFICATION_REVIEW
                         │
                         ▼
                  READY_FOR_EXTRACTION
                         │
                         ▼
        section detection → extraction → normalisation →
        validation → provenance          (Phase 3, not yet built)
```

Every branch ends in a **named outcome**, never an exception for an ordinary
"no" and never an empty string that reads like success.
`intelligence.document.contracts` holds the vocabulary: `OcrOutcome`,
`ClassificationStatus`, `CompletenessOutcome`, `Disposition`.

## What is built (Phase 2)

| Stage | Module | Behaviour |
|---|---|---|
| File validation | `ingestion/file_validation.py` | Type is read from the leading bytes, not the declared content type or extension. An executable renamed `report.pdf` is rejected with a specific reason. Mirrors the signatures in `apps.reports.scanning`. |
| Text layer | `ingestion/text_layer.py` | `pypdf` extraction; a PDF with fewer than `MIN_USABLE_CHARS` usable characters is treated as a scan and routed to OCR. A corrupt PDF is a "no", not a crash. |
| OCR | `ocr/` | `OCRProvider` protocol + `LocalTesseractProvider` + a registry. Output is tokens carrying `text`, `page`, `BoundingBox` (0..1), and `confidence`. When `pytesseract` or the Tesseract binary is missing, the result is `ENGINE_UNAVAILABLE` with no tokens - a scanned report is then held for review, not guessed. |
| Classification | `classification/keyword.py` | Deterministic weighted keyword vote. Every input is visible in `signals`. The winner must beat the runner-up by `2.0x` or the document is `REVIEW_REQUIRED` with no type. A learned classifier can replace this behind the same `classify()` signature. |
| Report schemas | `schemas/` | Per report type: fields, whether required, aliases, accepted units, plausibility bounds. `assess_completeness()` returns `COMPLETE / INCOMPLETE / AMBIGUOUS / INVALID / CONFLICTING` with the same precedence as `apps.reports.schema_engine`. Only the blood panels the CVD missing-data workflow needs are defined; narrative types (radiology, discharge) deliberately have **no** schema rather than one that always reads COMPLETE. |

`pipeline.process_document()` wires validation → text/OCR → classification and
returns a `DocumentResult` whose slots for the Phase 3 stages already exist.

## What is not built yet (Phase 3+)

`extraction/`, `normalization/`, `validation/`, `provenance/` are scaffolded
with intent docstrings only. The gold-standard benchmark, the finding
knowledge layer, and the small LLM module come after that, in that order.

## The OCR adapter

```python
from intelligence.document.ocr import default_provider, get_provider, register_provider
from intelligence.document.ocr.provider import OcrRequest

provider = default_provider()                 # deployment default, never None
result = provider.run(OcrRequest(image_bytes=data, media_type=media_type))
```

A deployment selects an engine with `DOCUMENT_OCR_PROVIDER=<name>` or registers
its own:

```python
register_provider("my-cloud-ocr", MyCloudOCRProvider)
```

Enabling local OCR needs the Python package **and** the system engine:

```
pip install -e ".[document]"      # pytesseract + Pillow
apt-get install tesseract-ocr     # or: brew install tesseract
```

Without the engine every path still works - scanned reports just route to
review, which is the pre-existing safe behaviour.

## Boundaries

* **The cardiovascular pathway must never import this package.**
  `tests/regression/test_cvd_isolation.py` enforces it with an AST import-graph
  check over `apps/risk`, `intelligence/ml_service` and
  `apps/common/intelligence.py`. A crash, hang or nonsense return from
  document intelligence cannot reach a risk assessment because none of that
  code is on the CVD engine's call graph.
* **OCR output is not clinical truth.** It carries confidence and provenance; a
  later stage decides whether to trust it.
* **A language model, when added, receives validated structured evidence** from
  this module - never a raw document, and never the job of extracting a value
  that was not validated deterministically first.

## Tests

`tests/document/` - ingestion, the OCR adapter (including every no-engine
path), classification and its abstentions, schema completeness precedence, and
the wired front-half pipeline. `tests/regression/test_ocr_never_fabricates.py`
pins the safe behaviour of the existing `apps.reports` pipeline so the new
module has to preserve it once the two are connected.
