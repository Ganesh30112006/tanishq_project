# CareSense AI — specification ↔ code map

This document maps each section of the master specification to where it is
addressed in the codebase. "Scaffolded" means the structure, data model and
safety default exist and the deeper implementation is a named next slice.

| Spec § | Topic | Where | State |
| --- | --- | --- | --- |
| 1 | Technology architecture | `pyproject.toml`, `config/settings/base.py`, `intelligence/` | Implemented |
| 2 | Responsibility split (Django vs FastAPI) | `config/`, `apps/` vs `intelligence/`; `apps/common/intelligence.py` | Implemented |
| 3 | High-level architecture / boundary | `apps/common/intelligence.py`, `intelligence/security.py` | Implemented |
| 4 | Codebase structure | `apps/*`, `intelligence/*`, `tests/*` | Implemented |
| 5 | Users & RBAC | `apps/accounts/models.py`, `apps/accounts/permissions.py`, migration `0002_seed_rbac` | Implemented |
| 6 | Resource-level authorization | `apps/authz/` (engine, relationships, policies, drf) | Implemented |
| 7 | Session & identity isolation | `apps/accounts/authentication.py` (revocation), `apps/audit/context.py` (contextvars, no globals) | Implemented |
| 8 | Database design | `apps/*/models.py`, FK/index/unique/check constraints, `VersionedModel`, `AppendOnlyModel` | Implemented |
| 9 | Clinical data states | `apps/common/enums.py::ClinicalDataState`; used by lab/health/report models | Implemented |
| 10 | Data provenance | `apps/medical_records/models.py::Provenance`, written per test by `apps/reports/pipeline.py` | Implemented |
| 11 | Report intelligence model | `apps/reports/models.py`, `apps/reports/serializers.py`, `apps/reports/views.py` | Implemented |
| 12 | Report processing pipeline | `apps/reports/pipeline.py` (all stages), `apps/reports/ocr.py` (pypdf text layer; image OCR = integration point), `intelligence/nlp` + `intelligence/ocr` endpoints, `apps/reports/jobs.py` | Implemented |
| 13 | Report classification | `apps/reports/pipeline.py::_classify` (uploader hint or keyword vote; ambiguous -> OTHER/REVIEW_REQUIRED) | Implemented |
| 14 | Expected report schema engine | `apps/reports/schema_engine.py`, `apps/reports/default_schemas.py`, migration `reports.0003` (seeded, versioned) | Implemented |
| 15 | Extraction confidence (OCR/entity/context separate) | `apps/reports/extraction.py` (per-field), `ReportTest.{ocr,entity,context}_confidence`, `Provenance.extraction_confidence` | Implemented |
| 16 | Deterministic data normalization | `apps/common/units.py` (versioned rules), `LabResultService.enter_result` | Implemented |
| 17 | Data-quality engine | `apps/data_quality/assessors.py` (runs on lab-result entry), `apps/data_quality/jobs.py` sweep, `apps/reports/pipeline.py::_validate` | Implemented |
| 18 | Outlier / anomaly detection (flag, never delete) | `apps/data_quality/assessors.py::detect_anomalies` (IQR + MAD over patient history -> `AnomalyFlag`), wired into `LabResultService` and the sweep job | Implemented |
| 19 | Duplicate detection | `apps/patients/identity.py` (layered: exact -> normalized -> composite -> Jaro-Winkler/Levenshtein), `apps/reports/pipeline.py::_reconcile` for duplicate reports | Implemented |
| 20 | Report reconciliation (preserve both + event) | `apps/reports/pipeline.py::_reconcile` (same-day / unit / duplicate conflicts -> `ReconciliationEvent`, both values kept) | Implemented |
| 21 | Temporal reasoning | `apps/common/temporal.py`, `observed/collected/reported/recorded` timestamps on models | Implemented |
| 22 | Missing-data engine (search before concluding absent) | `apps/common/enums.py::LookupState`, `apps/notifications/services.py::MissingDataService` | Implemented (states + tasks) |
| 23 | No-fabrication policy | `LabResultService` / `HealthMeasurementService` reject values in non-trustworthy states; sufficiency never imputes | Implemented |
| 24 | Data-sufficiency engine | `apps/risk/sufficiency.py::DataSufficiencyEngine` | Implemented |
| 25 | Missing-data task engine | `apps/notifications/models.py::MissingDataTask` (+ statuses) | Implemented |
| 26 | Missing-data notification routing (min necessary detail) | `apps/notifications/services.py::WORKFLOW_ROUTING`, `route_missing_data` | Implemented |
| 27 | Escalation (config policy, no hard-coded urgency) | `apps/notifications/models.py::EscalationPolicy` (seeded), `EscalationService.evaluate_overdue`, `missingdata.escalate` job + `run_escalation` command | Implemented |
| 28 | Risk engine flow | `apps/risk/views.py` (`POST /api/v1/risk/assessments`), `apps/risk/workflow.py`, `apps/risk/services.py`, `apps/risk/feature_assembly.py` | Implemented (end to end) |
| 29 | Task-specific models (no universal model) | `apps/risk/models.py::ModelVersion.task`, `RiskModel` per task | Implemented (registry) |
| 30 | Model validation | `intelligence/ml_service/train.py`: ROC-AUC/Brier, explicit row-identity leakage guard, subgroup + temporal (period) AUC, missing-data-robustness AUC; all stored in `ModelVersion.validation_metrics` | Implemented (demo) |
| 31 | Calibration | `intelligence/ml_service/train.py` (isotonic on held-out split), `intelligence/ml_service/router.py::_calibrate`; raw score never surfaced as a probability alone | Implemented |
| 32 | Out-of-distribution checking | `intelligence/anomaly/ood.py`; blocking verdicts persisted by Django | Implemented (contract) |
| 33 | Model registry | `apps/risk/models.py::ModelVersion` + `manage.py register_model` / `list_models` (from artifact meta.json) | Implemented |
| 34 | Reproducibility | `RiskAssessment` stores model/feature/preprocessing/calibration/explanation versions + input snapshot; append-only | Implemented |
| 35 | Explainable AI (SHAP != causation) | `intelligence/explainability/shap_runner.py` (exact linear attribution, `shap` when installed); `RiskFactor` direction/rank | Implemented |
| 36 | LLM / AI assistant (not the predictor) | `apps/ai/` (`AiAssistantService`, `ContextAssembler`), `intelligence/rag/` (`/v1/ai/answer`, extractive summarizer), `AiKnowledgeDocument` corpus | Implemented |
| 37 | AI/RAG security (auth -> scope -> minimize context -> audit) | `apps/ai/views.py::AiAskView` (RBAC `ai.use` + `visible_patient_queryset` + `authorize(USE_AI)`), `apps/ai/context.py` (minimized, per-report scoping), `intelligence/security.py` (token + correlation, no DB) | Implemented |
| 38 | AI output safety (distinguish observed/summary/interpretation/uncertainty) | `intelligence/rag/summarizer.py` (labelled sections, no fabrication), `apps/ai/services.py` (`_contains_disallowed` output validation, recorded not trusted) | Implemented |
| 39 | Report upload security (untrusted files) | `apps/reports/services.py::ReportService._validate_file` (type/size/ext/hash, private storage, no client paths) | Implemented |
| 40 | Database security | `config/settings/base.py` (env creds only, strict SQL mode, TLS option), `prod.py` | Implemented |
| 41 | Audit system | `apps/audit/` (`AuditLog` append-only, `AuditService`, action constants, metadata scrub) | Implemented |
| 42 | API design (versioned, DTOs, pagination, request ids) | `config/urls.py` `/api/v1/*`, `apps/common/pagination.py`, DRF serializers, `RequestContextMiddleware` | Implemented |
| 43 | Error contract | `apps/common/errors.py` (`ErrorCode`, `AppError` hierarchy, `drf_exception_handler`) | Implemented |
| 44 | Healthcare data retention | `AppendOnlyModel`, `supersedes`/`amends`/`addenda`, correction-as-new-row | Implemented |
| 45 | Notification security | `Notification.body` max length + min-detail templates | Implemented |
| 46 | Performance | Indexes on hot paths, scoped querysets, pagination, `select_related`; no global caching of patient data | Implemented (baseline) |
| 47 | Background processing (no Redis) | `apps/jobs/` (`Job` states, `JobService`, `runner.run_once`, `run_worker` command, `SKIP LOCKED`) | Implemented |
| 48 | Data-quality reporting | `GET /api/v1/reports/{id}/quality` (completeness / extraction reliability / validation / consistency / missing fields) | Implemented |
| 49 | Health data sufficiency example | `RiskAssessmentViewSet.create` → `RiskRequestWorkflow` (authorize → assemble from record → sufficiency → FastAPI → store; else missing-data task + notify) | Implemented |
| 50 | Report knowledge example | `apps/reports/pipeline.py` populates value/unit/dates/section/method/validation + conflict/freshness checks | Implemented |
| 51 | Full-record search before missing-data alert | `LookupState` + `MissingDataService.open_task(lookup_state=…)`; search assembly is the record-retrieval slice | Implemented (states) |
| 52 | Django ↔ FastAPI security boundary | `apps/common/intelligence.py` (payload only), `intelligence/security.py` (token + correlation id, no DB) | Implemented |
| 53 | Testing strategy | `tests/unit`, `tests/integration`, `tests/security` | Implemented (foundation set) |
| 54 | Non-negotiable security tests | `tests/security/test_patient_isolation.py`, `tests/integration/test_auth_flow.py` | Implemented |
| 55 | Code-quality rules | type hints, `from __future__ import annotations`, service layer, explicit transactions, centralized perms | Implemented |
| 56 | Django signal rule (explicit services, not signal chains) | services in every app; no domain logic in `save()` signals | Implemented |
| 57 | Model safety principle ("Prediction unavailable" is success) | `ServiceResult.blocked`, `RiskAssessment.Status.BLOCKED`, `tests/unit/test_risk_service_safe_block.py` | Implemented |
| 58 | End-to-end workflow | `RiskAssessmentService` + `MissingDataService` + `AuditService` + `NotificationService` | Implemented (risk path) |
| 59 | Final system behaviour (19 questions) | Traceable via audit + provenance + model registry + reproducibility fields | Implemented (data model) |
| -- | Identity: OIDC validation | `apps/accounts/oidc.py` (JWKS signature + iss/aud/exp; fails closed), wired into `BearerTokenAuthentication` | Implemented |
| -- | API surface completion | endpoints for `/labs`, `/records`, `/health`, `/alerts`, `/notifications/tasks`, `/reconciliation`, `/patients/identity`; OpenAPI at `/api/schema` + `/api/docs` (drf-spectacular) | Implemented |
| -- | MySQL CI + contract test | `.github/workflows/ci.yml` (SQLite + MySQL 8 matrix), `config/settings/ci.py`, `tests/integration/test_intelligence_contract.py` | Implemented |
| 60 | Final engineering objective | Fail-safe defaults everywhere the deeper slice is not yet built | Implemented (posture) |

## Request lifecycle (risk assessment)

1. `RequestContextMiddleware` assigns a correlation id and binds request-scoped
   context (contextvars — no globals).
2. DRF authenticates the bearer token (`BearerTokenAuthentication`); revoked /
   expired tokens fail here.
3. RBAC: `HasPermission.of("risk.request")` gates the coarse capability.
4. Resource authorization: the view scopes its queryset
   (`visible_patient_queryset`) and `ResourceAccessPermission` re-checks the
   specific object through the policy engine — **before** data is returned.
5. The view assembles authorized, patient-scoped feature values from the record.
6. `RiskAssessmentService`: resolve active `ModelVersion` → `DataSufficiencyEngine`
   → if not `SUFFICIENT`, persist a `BLOCKED` assessment, open a
   `MissingDataTask`, route a minimal notification, return a safe result.
7. If sufficient: `IntelligenceClient.infer` sends only the feature payload +
   model/task ids + correlation id to FastAPI.
8. FastAPI runs inference → calibration → reliability/OOD → SHAP and returns a
   result. Without a registered artifact it returns `REVIEW_REQUIRED`.
9. Django applies the reliability verdict, persists a version-stamped,
   append-only `RiskAssessment` (+ `RiskFactor` rows) and writes an audit row.
