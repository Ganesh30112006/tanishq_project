# Running this in earnest

What has to be true before real patients touch this, and how to check each of
them. Everything here is enforced or reported by code, not by convention.

## Processes

Four, and the third is the one people forget:

| Process | Command | If it stops |
|---|---|---|
| Django API | `manage.py runserver` / gunicorn | Obvious — requests fail |
| Intelligence service | `uvicorn intelligence.main:app --port 9001` | Risk requests return `UPSTREAM_UNAVAILABLE` |
| **Job worker** | `manage.py run_worker` | **Nothing appears to fail.** Uploads still return 201 and every report sits at `RECEIVED` forever |
| Frontend | `pnpm --filter @workspace/caresense-ai run dev` | Obvious |

The worker is dangerous precisely because its failure is silent — the queue is
a database table, so nothing raises when nobody is draining it. That is what
`/readyz` exists for.

## Health endpoints

| Endpoint | Question | Use it for |
|---|---|---|
| `/healthz` | Is this process serving HTTP? | Liveness probe |
| `/readyz` | Can the system do its work? | Readiness probe, monitoring, paging |

They are deliberately different. `/healthz` touches nothing else: wiring a
database check into a liveness probe turns a database outage into a container
restart loop. `/readyz` checks the database and the job pipeline, returns 503
when work is queued and no worker has reported in 90 seconds, and names the fix
in its response:

```json
{"status": "unavailable",
 "checks": {"jobs": {"status": "down",
   "problems": ["No worker has reported in 90s and 3 job(s) are waiting.
                 Uploaded reports are not being processed.
                 Start one with: manage.py run_worker"]}}}
```

It is unauthenticated and returns only counts and states — no identifiers,
nothing worth reading if it were exposed.

## Uploads

Report uploads are public, untrusted input. The extension and the
`Content-Type` header both come from the uploader, so neither is evidence of
anything: `payload.exe` renamed to `report.pdf` satisfies both.

Two layers, and **the first cannot be switched off**:

1. `apps/reports/scanning.py` always runs. It verifies the leading bytes match
   the claimed type, names what the file actually is when they do not, rejects
   PDFs carrying JavaScript, launch actions, embedded files or auto-run
   actions, and catches the EICAR test string. This used to be a no-op unless
   an operator configured a scanner — a deployment that forgot the setting
   accepted anything at all.
2. `REPORT_UPLOAD_SCANNER` adds a real antivirus engine. **Production refuses
   to start without it**, because the built-in layer is a content-type gate and
   recognises no malware families.

Downloads are served with the content type the file was *verified* to be, never
the one the uploader declared — echoing that back is how a stored file becomes
stored XSS.

## Sessions

Access tokens last an hour. Refresh tokens last 14 days and are **single-use**:
every redemption issues a new one and retires the access token it replaced.

The property that makes a long-lived credential acceptable is what happens on
reuse. A legitimate client discards its refresh token the moment it redeems
one, so a *second* presentation means two parties hold it. There is no way to
tell the thief from the victim, so the whole rotation family is revoked and
both must sign in again. A forced re-login is a much better outcome than a
silently shared session.

Signing out revokes the refresh token too — otherwise "sign out" leaves a
credential that mints a new session.

## Consent, retention and erasure

Run `manage.py check_privacy` to see the state of all three.

**Consent is per purpose**, so withdrawing agreement to AI summaries does not
end the record itself. Enforcement switches on per purpose when its wording is
published (`manage.py seed_consent`): enforcing before anything is published
would block every deployment on day one, and never enforcing would make consent
decorative, so publishing is the deliberate act — and `check_privacy` reports
any purpose still unpublished so the gap is visible rather than silent.
Absence of a grant is never treated as consent.

**Erasure is de-identification, not deletion**, and the system says so in those
words. Clinical history is append-only and separately subject to a retention
obligation, so "delete my data" cannot be a `DELETE`. What is destroyed: name,
date of birth, phone, record number, and the login with every credential it
holds. What survives: the measurements and results, attached to a record that
identifies nobody. The person is told exactly that, including the date before
which the retained rows may not be destroyed. Carrying one out is never
self-service — a named person decides and the decision is audited.

**Retention is report-first.** `manage.py apply_retention` prints what has
expired and does nothing. `--apply` acts only on categories with no evidentiary
value — expired credentials and delivered notifications. Clinical records,
uploaded reports and the audit log are never destroyed by a cron job; they are
listed for a person to decide on. Every policy carries a stated `basis`,
because "we kept it for eight years" is only defensible if someone can say
which obligation required eight years.

The default periods are starting points that a compliance owner must review
against the obligations that actually bind the deployment. They are not legal
advice.

## Model governance

`register_model` always lands a *new* version in `DRAFT`. Making it serve
patients requires `govern_model` with a named approver and a recorded reason.
The synthetic demonstration models are `RETIRED` and cannot serve.

**A version that has left `DRAFT` is immutable.** Re-registering a
byte-identical artifact is a no-op, so provisioning scripts are safe to re-run;
re-registering anything *different* is refused and names what differs. This
closed two silent failures. `RETIRED` had not actually been terminal - a
withdrawn model could be brought back simply by registering it again, which is
how `seed_demo` came to hand the live `cvd` task to a model fitted on invented
data. And a version identifier had not actually identified anything - the
registry row behind `cvd-nhanes-logreg:3.0.0` could be rewritten to describe a
different model, so a `RiskAssessment` recorded months earlier would no longer
reconstruct. The `FeatureSchema`, which holds the `valid_domain` gate that
refuses out-of-range patients, is checked in its own right.

`seed_demo` will not take the `cvd` task from a model it did not install, and
says so rather than doing it quietly.

`/readyz` does not check any of this, deliberately: a model being retired is a
governance state, not an outage.

Check what is actually serving:

```bash
python manage.py shell -c "from apps.risk.models import RiskModel;   m = RiskModel.objects.get(task='cvd');   print(m.active_version.model_id, m.active_version.version, m.is_enabled)"
```

## Clinical validation

`register_model` and `govern_model` check that a *person* approved a model.
They do not check whether the model is defensible. That is a separate run:

```bash
python -m intelligence.ml_service.clinical_validation --version <version>
```

It measures coverage, abstention, subgroup reliability and clinical utility
against `intelligence/ml_service/acceptance_criteria.py`, which states every
threshold and the clinical reason for it. It exits non-zero when a criterion
fails and writes `cvd-<version>.clinical.json` beside the model card.

**Run it before advancing a version to `APPROVED_FOR_EVALUATION`,** and put the
result in the transition reason. The current model passes 9 of 10; the open
failure is recorded below rather than waived.

### Open finding: unequal coverage

`coverage.group_disparity` fails at 2.06x against a 1.5x ceiling. Black
non-Hispanic participants are refused at 8.80% and Other/multiple at 10.43%,
against 5.07% for White non-Hispanic. Almost all of it is a missing systolic
blood-pressure reading, so nothing in the model or the code will fix it - it is
a measurement-completeness problem wherever the readings are taken. It is
tracked here because unequal coverage is unequal care and appears in no
accuracy metric.

### A version means one model, including its schema

Adding `risk_direction` to the feature schema required a new model version -
3.0.0 was already approved, and an approved schema is immutable, so
`register_model` refused the change. The estimator in 3.1.0 is byte-identical
to 3.0.0; only the schema differs. That is the rule working as intended: the
`valid_domain` gate lives in the schema, so a schema that can be edited under an
approved version is a gate that can be edited under an approved version.

## Document intelligence: turning it on

`DOCUMENT_INTELLIGENCE_MODE` decides how much the service is allowed to affect
a report. It ships as **`off`**, and an unrecognised value falls back to `off`
so a typo cannot enable a clinical path.

| Mode | Effect |
|---|---|
| `off` | not called. Behaviour is exactly as it was before the integration |
| `shadow` | called; what it said is recorded in the audit trail under `second_reader`; the outcome is untouched |
| `advisory` | called; may hold for review a report the pipeline would have finalized. It can never do the reverse |

**Run `shadow` first.** It costs one service call per report and produces the
only thing that could justify `advisory`: a record of where the two readers
disagreed, on real reports, before anything acts on it.

That record is written for every report the service is consulted about, in
`shadow` and `advisory` alike, and is kept against the outcome the existing
pipeline reached *before* any second opinion - so an advisory hold does not
erase the fact that the two readers differed.

```
python manage.py shadow_disagreements                    # the summary
python manage.py shadow_disagreements --unclassified     # what needs a person
python manage.py shadow_disagreements --kind VALUE_DIFFERS
python manage.py shadow_disagreements --classify <id> --as PARSER_ERROR     --by "dr-mehta" --note "the second reader took the next row's unit"
```

The summary counts kinds of disagreement, not agreement. Two readers can agree
and both be wrong, so an agreement percentage says how similar they are, not
whether either is right; it is printed at the bottom, labelled as such. What is
worth watching:

| Count | What it means |
|---|---|
| unsafe disagreements | both readers produced a number they stand behind, and the numbers differ. One is wrong and nothing in the outputs says which |
| safe abstentions | the second reader read the line and would not stand behind it. Safe by construction: an abstention can only hold a report |
| newly detected evidence | results only the second reader found. Candidates for a real gain *and* candidates for fabrication - the document decides |
| missed evidence | results only the existing pipeline found |
| conflict detection | the same analyte printed twice with results that disagree after conversion |
| routing differs | one reader would have held the report and the other would not |

**Fabrications cannot be counted here**, and the command says so rather than
producing a number. A fabrication is a value the report does not support, and
neither reader knows what the report says. That is what the extraction
benchmark measures; this table only shows where to look.

**Nothing is classified automatically.** Which reader was wrong needs the
document, so the machine fills in only the three classes that follow from the
responses themselves - `SAFE_ABSTENTION`, `CONFLICT_DETECTION`, `OCR_FAILURE` -
and leaves the rest `UNKNOWN`. A ruling requires a named reviewer and a written
reason: the counts are already known, and the reason is the only part that says
what to change.

The comparison is a research record. No clinical code reads it, a test enforces
that, and a failure to write it cannot affect the report.

Nothing the service returns is persisted as a clinical value in any mode, and a
service failure is always "no opinion" rather than a blocked report. The mode
therefore changes how conservative the pipeline is and nothing else.

## Document intelligence runtime requirements

Document processing runs in the FastAPI intelligence service and is reached
only over HTTP (`POST /v1/documents/process`). Django sends the authorized
document *content*; the service never resolves a path or a patient id itself.

Which stages can actually run depends on what is installed. `GET
/v1/documents/capabilities` reports this live, and every
`/v1/documents/process` response carries a `capabilities` block, so
availability is observable rather than assumed.

| Capability | Dependency | If the dependency is missing |
|---|---|---|
| PDF text-layer extraction | `pypdf` (always installed) | a scanned PDF yields no text and routes to review; it never fails the request |
| OCR (photos, scans) | `pytesseract` + the Tesseract **engine** (system package) | result is `OCR_UNAVAILABLE` / `UNREADABLE`, no tokens, no clinical rows — the report is held for human review, never guessed |
| Classification | in-repo, deterministic | always available |
| Extraction / normalisation / validation | in-repo, deterministic | always available |
| LLM narrative | not implemented | fails closed — capability reports `available: false` |
| RAG / knowledge retrieval | not implemented | fails closed |

To enable OCR in a deployment:

```
pip install -e ".[document]"        # pytesseract + Pillow
apt-get install tesseract-ocr       # Debian/Ubuntu
# or: brew install tesseract         # macOS
```

Select a non-default engine with `DOCUMENT_OCR_PROVIDER=<name>`; register a
custom provider via `intelligence.document.ocr.register_provider`.

The deliberate design choice: when OCR is unavailable the pipeline degrades to
"needs review", never to a fallback parser that produces plausible-looking
values. A missing capability is safe; a fabricated clinical value is not.

## What CI covers

`.github/workflows/ci.yml`, at the repository root — an earlier copy lived at
`Backend/.github/workflows/`, where GitHub Actions never looks, so it had never
run once and the MySQL job had never proved anything.

| Job | Runs |
|---|---|
| `backend-sqlite` | Every push |
| `backend-mysql` | Every push — MySQL 8 is the production target |
| `lint` | Every push |
| `migrations-are-complete` | Every push — a model edited without a migration passes every test and then fails on deploy |
| `frontend` | Every push — typecheck and tests |
| `model-pipeline` | Weekly and on demand — downloads ~58 MB from the CDC, so it does not gate a push |

Lint enforces every substantive rule. `E501` (line length) is deferred with the
reason recorded in `pyproject.toml`: 142 pre-existing lines exceed 100
characters, `ruff format` would fix nearly all of them but rewrites 192 of 321
files, and burying every real change in a formatting diff is worse than the
lines being long. It is a one-commit pass someone should make deliberately.
