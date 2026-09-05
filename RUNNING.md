# Running CareSense AI locally (frontend + backend)

Three processes, each in its own terminal, from the paths below.

## 1. FastAPI intelligence service

```bash
cd Backend
. .venv/Scripts/activate            # PowerShell: .venv\Scripts\Activate.ps1
uvicorn intelligence.main:app --port 9001
```

## 2. Django API

```bash
cd Backend
. .venv/Scripts/activate
# .env (copied from .env.example) should set at least:
#   DJANGO_SETTINGS_MODULE=config.settings.dev
#   DJANGO_SECRET_KEY=<anything for local dev>
#   DJANGO_DB_BACKEND=sqlite
#   LOCAL_DEV_TOKENS=true
#   CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
python manage.py migrate
python manage.py seed_demo           # optional: demo users + patients + a real risk assessment
python manage.py runserver 127.0.0.1:8000
```

`seed_demo` prints the demo accounts it creates (one per role) and the shared
password. Run it again after the FastAPI service is up if you ran it before
FastAPI was reachable — it's idempotent and will fill in the risk assessments
it skipped the first time.

## 3. Frontend (Vite dev server)

```bash
cd Frontend
pnpm install                         # first time only
cp artifacts/caresense-ai/.env.example artifacts/caresense-ai/.env.local
pnpm --filter @workspace/caresense-ai run dev
```

Open the printed URL (default `http://127.0.0.1:5173`) and sign in with one
of the `seed_demo` accounts.

## Regenerating the API client after a backend change

The frontend's typed API client (`lib/api-client-react`, `lib/api-zod`) is
generated from `Frontend/lib/api-spec/openapi.yaml` — a hand-maintained
description of the real Django endpoints (Django's own drf-spectacular schema
is close but not 1:1, since a few endpoints — dashboard summary, patient
timeline/AI-summary, presentation fields on `Patient` — are Django-side
composition rather than raw resource CRUD). After changing a Django
serializer/view that the frontend depends on:

1. Update `Frontend/lib/api-spec/openapi.yaml` to match.
2. `cd Frontend/lib/api-spec && ./node_modules/.bin/orval --config ./orval.config.ts`
3. **Check `Frontend/lib/api-zod/src/index.ts`** — orval's zod generator
   rewrites this file on every run and re-adds a trailing
   `export * from './generated/types';` that collides with the curated
   `export type { ... } from "./generated/types"` block above it (both
   export a same-named `GetXParams` type from two different modules). Delete
   that trailing line after every regeneration.
4. `cd Frontend && pnpm run typecheck:libs`

## Notes

- Decimal fields (risk scores, SHAP contributions, confidences) come back
  from Django as JSON **strings**, not numbers — DRF's `DecimalField` avoids
  floating-point precision loss by serializing to string
  (`COERCE_DECIMAL_TO_STRING`). `openapi.yaml` types them `string`; parse
  with `Number(...)` in the UI where you need to do arithmetic on them.
- SQLite (the local dev database) is configured with WAL journaling and a
  busy timeout (`config/settings/base.py`) so ordinary concurrent requests
  don't collide. It's still a single-writer database and is only ever a dev
  convenience — the real target is MySQL 8.x.
- The Express project under `Frontend/artifacts/api-server` and the design
  tool under `Frontend/artifacts/mockup-sandbox` are unrelated to this app —
  the real frontend (`Frontend/artifacts/caresense-ai`) talks directly to
  Django over CORS, per the backend's own architecture (Django is the only
  API layer clients ever call).
