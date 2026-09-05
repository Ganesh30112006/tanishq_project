# CareSense AI — Backend

An evidence-aware, auditable healthcare / public-health **decision-support**
backend. It is deliberately **not** an autonomous diagnostic or treatment
system: it structures validated healthcare information, checks whether the
evidence is sufficient, produces a reliable prediction **only when justified**,
explains it, and otherwise **fails safely**.

> When information is missing: do not guess — find, validate, check history,
> check freshness, check conflicts, then use valid data, request the missing
> data, or block the prediction.

## Architecture at a glance

| Concern | Owner |
| --- | --- |
| Identity, authorization, RBAC, resource-level access, patient scope, business state, primary database, API layer, audit | **Django + DRF** (`config/`, `apps/`) |
| ML inference, calibration, OOD/reliability, SHAP, OCR, NLP/entity extraction, report classification, RAG/LLM orchestration | **FastAPI** (`intelligence/`) |

Clients talk **only** to Django. Django is the only caller of the FastAPI
intelligence service, and sends it only a validated, patient-scoped feature
payload plus a model/task id and a correlation id — never raw database ids the
service could use to fetch records itself.

```
Web / Mobile ──▶ Django REST API ──┬──▶ MySQL 8
                                   ├──▶ Report workflow (DB-backed jobs)
                                   └──▶ FastAPI intelligence service
                                          ├─ ML inference ─▶ calibration ─▶ SHAP / OOD
                                          ├─ document intelligence (OCR / classify)
                                          └─ AI / RAG orchestration
                     results ◀──────────────┘
                Django: store + audit ──▶ MySQL
```

## Technology

* **Django 5.1**, **Django REST Framework**, Django ORM + migrations
* **MySQL 8.x** as the transactional source of truth (`STRICT_TRANS_TABLES`)
* **FastAPI** + **Pydantic v2** for the intelligence service
* Data/ML (intelligence extra): Polars, NumPy, scikit-learn, XGBoost, SHAP;
  PyTorch only where a task/data justifies it
* **Pytest** + `pytest-django` for unit / integration / security / ML tests
* OpenTelemetry-compatible instrumentation (optional, `observability` extra)
* OAuth 2.0 / OpenID Connect–compatible identity; revocable bearer tokens

No IoT, Redis, Kafka, brokers, or unnecessary microservices. Background work is
a database-backed job table polled with `SELECT … FOR UPDATE SKIP LOCKED`.

## Layout

```
config/                 Django project (settings/, urls, wsgi/asgi, observability)
apps/
  common/               enums, structured errors, model bases, units, temporal, intelligence client
  accounts/             User, Role, Permission, RBAC resolver, revocable tokens, OIDC-compatible auth
  authz/                resource-level policy engine (ROLE+PERMISSION+RESOURCE+RELATIONSHIP+ACTION)
  audit/                append-only audit trail + request-context middleware
  patients/ doctors/    patients, doctors, doctor–patient assignments
  laboratories/         labs, lab techs, orders, results (+ deterministic unit normalization)
  medical_records/      history, conditions, medications, symptoms, clinical notes, provenance
  health/               vital-sign / point measurements with clinical-data-state
  reports/              report intelligence model + intake pipeline + versioned schema engine
  risk/                 model registry, feature schemas, data-sufficiency engine, reproducible assessments
  alerts/ notifications/ alerts, notifications, missing-data task engine + workflow routing
  reconciliation/       preserve-both conflict events
  data_quality/         deterministic quality checks + outlier flagging (never auto-delete)
  ai/                   AI assistant interaction records + guardrails
  jobs/                 DB-backed background jobs + worker command
intelligence/           FastAPI app: ml_service, report_service, nlp, ocr, features, anomaly, calibration, explainability
tests/                  unit / integration / security
```

`docs/ARCHITECTURE.md` maps the specification's sections to the code.

## Local development

Prerequisites: Python 3.11+. A MySQL server is **not** required for the test
suite (it uses in-memory SQLite); the app itself targets MySQL 8.

```bash
python -m venv .venv
. .venv/Scripts/activate           # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev,intelligence]"
cp .env.example .env               # then edit

# Django (SQLite by default in dev; set DJANGO_DB_BACKEND=mysql for MySQL)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

# Background worker (separate process) - runs report/reconciliation jobs
python manage.py run_worker

# Scheduled maintenance jobs (run periodically, e.g. from cron)
python manage.py run_escalation      # advance overdue missing-data tasks
python manage.py run_quality_sweep   # backfill data-quality + anomaly flags

# FastAPI intelligence service (separate process)
uvicorn intelligence.main:app --port 9001

# Train + register the demo risk model (separate, controlled ML pipeline)
python -m intelligence.ml_service.train --task cvd --version 1.0.0 --out intelligence/_artifacts
python manage.py register_model --meta intelligence/_artifacts/cvd-1.0.0.meta.json --activate
python manage.py list_models
```

### Tests

```bash
pytest                     # all (SQLite)
pytest tests/security      # patient-isolation / IDOR / privilege escalation
pytest tests/unit          # validators, unit conversion, permissions, sufficiency, routing
pytest tests/ml            # calibration, OOD, SHAP, leakage, subgroup/temporal metrics

# Against a real MySQL 8 (matches CI)
DJANGO_SETTINGS_MODULE=config.settings.ci MYSQL_HOST=127.0.0.1 MYSQL_USER=root \
  MYSQL_PASSWORD=root MYSQL_DATABASE=caresense_test pytest -q
```

## Non-negotiable behaviours (enforced by tests)

* Patient A → Patient B data **fails**; doctor → unassigned patient **fails**;
  lab tech → unrelated clinical info **fails**; a client-supplied role/`patient_id`
  never changes authorization; revoked tokens **fail**.
* Authorization is applied **before** data is returned (scoped querysets +
  object-level checks) — never fetch-broad-then-filter.
* Missing clinical measurements are never replaced with a mean / median /
  model output / population average.
* Conflicting clinical values are preserved and routed to reconciliation,
  never silently merged.
* `Prediction unavailable` (`INSUFFICIENT_DATA`, `OUT_OF_DOMAIN`,
  `CONFLICTING_DATA`, `REVIEW_REQUIRED`, …) is a **successful** outcome.
* Audit rows and historical clinical observations are append-only.

## Status

Implemented end to end:

* **Identity & authorization** — accounts/RBAC, the resource-level
  authorization engine, revocable tokens, append-only audit.
* **Risk-assessment slice** — `POST /api/v1/risk/assessments` authorizes,
  assembles authorized feature values from the record, runs the
  data-sufficiency engine, calls the intelligence service, stores a
  version-stamped append-only assessment, and on a block opens
  workflow-routed missing-data tasks and notifies the requester.
* **Report-intelligence pipeline** — `POST /api/v1/reports/` validates the
  untrusted file, stores it privately, and enqueues a background job that runs
  the deterministic pipeline: text → classification → sections → entity
  extraction → terminology/unit normalization → temporal extraction →
  deterministic validation → completeness analysis (versioned schema engine) →
  provenance → reconciliation (preserve both) → `FINALIZED` or
  `REVIEW_REQUIRED`. Plus `/{id}/quality`, `/{id}/reprocess`, `/{id}/file`.
* **ML inference** — the intelligence service loads a calibrated model
  artifact bundle, produces a calibrated probability, an OOD/reliability
  verdict, and additive SHAP-style feature contributions; a separate,
  reproducible training pipeline (`intelligence.ml_service.train`) builds the
  bundle and `manage.py register_model` records its metadata in the Django
  registry.
* **AI assistant / RAG** — `POST /api/v1/ai/ask` (authorized doctor, assigned
  patient). Django assembles a *minimized* patient-scoped context, calls the
  AI service with that context + approved general knowledge + a correlation
  id, then validates and records the output as an `AiInteraction`. The service
  answer is extractive — it restates only what the context contains, split
  into OBSERVED DATA / AI SUMMARY / INTERPRETATION / UNCERTAINTY / MISSING
  INFORMATION — and never invents a medical fact. Output is never written to a
  clinical record. No authorized context ⇒ a safe non-answer. A real LLM slots
  in behind the same contract with the same output validation.

* **Full API surface** — CRUD/workflow endpoints for `/labs` (orders, result
  entry, validation), `/records` (conditions, medications, symptoms, append-only
  clinical notes), `/health` (measurements), `/alerts` (+ acknowledge/resolve),
  `/notifications/tasks` (missing-data task list + transitions),
  `/reconciliation/events` (review + resolve) and `/patients/identity`
  (candidate review + merge). OpenAPI 3 at `/api/schema`, Swagger UI at
  `/api/docs`.
* **Real OCR / NLP** — the pipeline extracts embedded-text-layer PDFs with
  `pypdf`; the FastAPI `nlp`/`ocr` endpoints do rule-based entity extraction
  with negation/uncertainty flags and text normalization. Image OCR is a named
  integration point.
* **Data-quality + anomaly detection** — `apps/data_quality/assessors.py` runs
  on every lab-result entry (validity / unit / timeliness / plausibility →
  `DataQualityEvent`) and flags temporal outliers with IQR + MAD →
  `AnomalyFlag` (never deletes). A `dataquality.sweep` job backfills.
* **Missing-data escalation** — configurable `EscalationPolicy` per workflow;
  `EscalationService` / the `missingdata.escalate` job advance overdue tasks
  one policy step at a time (raise priority, re-route), from validated policy
  only.
* **Patient-identity resolution** — layered resolver (exact → normalized →
  deterministic composite → Jaro-Winkler/Levenshtein), never auto-merges;
  every candidate becomes a PENDING review + an `IDENTITY_CONFLICT` event, and
  a merge re-points clinical rows and deactivates (never deletes) the duplicate.
* **Model validation** — training records a row-identity leakage guard,
  subgroup and temporal (period) ROC-AUC, and missing-data-robustness AUC.
* **Federated identity** — real OIDC access-token validation
  (`apps/accounts/oidc.py`): JWKS signature + `iss`/`aud`/`exp`, fails closed.
* **CI** — `.github/workflows/ci.yml` runs the suite on SQLite and against a
  real MySQL 8 service (`config/settings/ci.py`); a contract test exercises
  Django's `IntelligenceClient` against the real FastAPI app.

The AI answerer ships as a deterministic extractive summarizer (safest
possible default); a hosted LLM is a drop-in behind
`intelligence/rag/summarizer.py`. Image OCR and a private object-store file
backend are configuration points (`DJANGO_FILE_STORAGE`, `REPORT_UPLOAD_SCANNER`).
