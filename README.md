# Human-in-the-Loop Prompt Improvement System

An LLM triages bug reports into structured JSON. A human reviewer corrects the
output. The corrections are stored, used to build a new prompt version, and a
deterministic evaluation proves whether the new prompt is actually better -
including whether it broke anything that used to work.

```
bug report ──> LLM triage ──> human correction ──> stored
                                                     │
                          ┌──────────────────────────┘
                          v
              new prompt version (few-shot + calibration)
                          │
                          v
      evaluation on held-out examples: previous version vs active
                 accuracy delta · regression count
```

**Stack:** React + Vite + Tailwind · FastAPI · Supabase Postgres · OpenRouter
(`deepseek/deepseek-v4-flash`).

---

## Table of contents

- [How the loop works](#how-the-loop-works)
- [Repository layout](#repository-layout)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Database schema](#database-schema)
- [Running locally](#running-locally)
- [Demo workflow](#demo-workflow)
- [API reference](#api-reference)
- [Tests](#tests)
- [Deployment](#deployment)
- [Assumptions](#assumptions)
- [Limitations](#limitations)

---

## How the loop works

1. **Seed** - 111 bug reports are split into two disjoint sets: 93 go into the
   review pool (`bug_reports`), 18 into a held-out gold set
   (`evaluation_examples`) with expected severity and component labels.
2. **Triage** - the reviewer picks a report and runs the LLM. The backend sends
   the *active* prompt to OpenRouter and stores the returned JSON.
3. **Correct** - the reviewer edits severity, component and rationale, and
   saves. The correction is written to `bug_reports.human_corrected_json` and an
   immutable audit row is appended to `review_events`.
4. **Improve** - "Improve Prompt" builds a new prompt version from every stored
   correction and marks it active. The generated text is stored in
   `prompt_versions`. A stable operating structure and decision process live in
   `prompt_service.py`; calibration rules and reference cases are generated
   deterministically from the current human corrections.
5. **Evaluate** - "Run Evaluation" scores the active prompt against the
   **immediately previous prompt version** on the held-out set and reports
   accuracy, delta and regressions. The previous version's score is reused from
   its last stored run rather than recomputed, so a run costs one LLM call per
   example instead of two.

The split in step 1 is the point of the whole design: the improved prompt is
built from the review pool and scored on text it has never seen, so a gain is a
gain and not recall.

---

## Repository layout

```
.
├── README.md
├── DESIGN.md                  architecture, tradeoffs, production notes
├── client/                    React + Vite + Tailwind frontend
│   ├── src/components/        BugList, BugDetail, TriageForm, ControlPanel, …
│   └── src/lib/               api client, reviewer id, label vocabulary
├── server/                    FastAPI backend
│   ├── app/
│   │   ├── config.py          env-driven settings
│   │   ├── db.py              Supabase PostgREST client
│   │   ├── llm.py             OpenRouter client (JSON-schema constrained)
│   │   ├── grading.py         deterministic scoring - no model involved
│   │   ├── prompt_service.py  prompt version assembly
│   │   ├── evaluation.py      baseline vs active orchestration
│   │   └── routes/            health, bugs, prompts, evaluation
│   └── tests/                 42 unit + loop tests
└── supabase/
    ├── schema.sql             tables, constraints, indexes, RLS
    └── seed.sql               baseline prompt + 111 bug reports
```

---

## Setup

### Prerequisites

- Python 3.11+ (tested on 3.14)
- Node 20+ (tested on 25)
- A Supabase project (free tier is enough)
- An OpenRouter API key with credit

### 1. Database

In the Supabase SQL editor, run the two files in order:

```bash
supabase/schema.sql
supabase/seed.sql
```

Or from the CLI, using the connection string from
**Project Settings → Database → Connection string → URI**:

```bash
psql "$SUPABASE_DB_URL" -f supabase/schema.sql && psql "$SUPABASE_DB_URL" -f supabase/seed.sql
```

`seed.sql` is idempotent: bootstrap blocks skip populated tables and expanded
review reports are inserted only when their exact text is missing. Re-running
it never duplicates data or destroys your corrections.

### 2. Backend

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cp .env.example .env
```

Then fill in `server/.env` (see [Environment variables](#environment-variables)).

### 3. Frontend

```bash
cd client && npm install && cp .env.example .env
```

---

## Environment variables

Secrets live only in `.env` files, which are git-ignored. Only `.env.example`
files are committed. **No key of any kind belongs in the repository.**

### `server/.env`

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `SUPABASE_URL` | yes | - | e.g. `https://abcdefgh.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | - | Server-side only. Bypasses RLS; must never reach the browser. |
| `OPENROUTER_API_KEY` | yes | - | From openrouter.ai |
| `OPENROUTER_BASE_URL` | no | `https://openrouter.ai/api/v1` | |
| `OPENROUTER_MODEL` | no | `deepseek/deepseek-v4-flash` | |
| `LLM_TEMPERATURE` | no | `0` | Kept at 0 so evaluation reruns are comparable. |
| `LLM_SEED` | no | `7` | Same reason. |
| `LLM_TIMEOUT_SECONDS` | no | `25` | Sets the worst-case evaluation duration, not the typical one. |
| `EVAL_CONCURRENCY` | no | `8` | Total in-flight LLM calls, shared across both arms. Raise cautiously - rate-limit errors score as incorrect. |
| `MAX_FEW_SHOT_EXAMPLES` | no | `6` | Maximum distinctive disagreements embedded as reference cases. |
| `CORS_ALLOW_ORIGINS` | no | `http://localhost:5173` | Comma-separated. Set to your Pages URL in production. |

### `client/.env`

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | no | `http://localhost:8000` | Anything prefixed `VITE_` is inlined into the public bundle - never put a secret here. |

> The frontend never talks to Supabase or OpenRouter directly. It only calls the
> FastAPI backend, so no credential is ever shipped to the browser.

---

## Database schema

Six tables, defined in [`supabase/schema.sql`](supabase/schema.sql).

| Table | Purpose |
| --- | --- |
| `bug_reports` | Review pool: report text, LLM output, human correction, status, prompt version used, reviewer, timestamps |
| `review_events` | Append-only audit trail: what a correction replaced, who made it, when |
| `prompt_versions` | Every prompt, including generated ones. Exactly one is active |
| `evaluation_examples` | Held-out gold set with expected labels |
| `evaluation_runs` | One row per prompt version per evaluation: accuracies + regression count |
| `evaluation_results` | Per-example detail backing each run |

Notable constraints:

- Severity and component vocabularies are enforced by `CHECK` constraints, so a
  bad label fails at write time instead of silently corrupting accuracy.
- A partial unique index (`prompt_versions_single_active`) makes "two active
  prompts at once" unrepresentable.
- RLS is enabled with **no** policies. The backend uses the service-role key,
  which bypasses RLS; nothing else can read these tables.

---

## Running locally

Two terminals.

**Backend** (from `server/`):

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**Frontend** (from `client/`):

```bash
npm run dev
```

Open http://localhost:5173. Interactive API docs are at http://localhost:8000/docs.

Check configuration at any time:

```bash
curl -s http://127.0.0.1:8000/health
```

`/health` reports each credential as a boolean and lists what is missing. It
never echoes a secret value.

### If port 8000 is already taken

Run uvicorn on another port and point the client at it:

```bash
.venv/bin/uvicorn app.main:app --reload --port 8010
```

Then set `VITE_API_BASE_URL=http://127.0.0.1:8010` in `client/.env`.

> Prefer `127.0.0.1` over `localhost`. On machines where `localhost` resolves to
> `::1` first, it can reach a different process listening on IPv6 than the
> uvicorn server bound to IPv4 - which produces confusing "wrong response"
> behaviour rather than a clean connection error.

### Optional: same-origin dev proxy

`vite.config.js` proxies `/api` → `http://127.0.0.1:8000`. Set
`VITE_API_BASE_URL=/api` to route through it and avoid CORS entirely in
development. This is dev-only; production builds must use the absolute backend
URL.

---

## Demo workflow

1. Open the app. The left pane lists 93 seeded reports; the right pane shows
   `v1-baseline` active and "No previous evaluation".
2. Click **Run Evaluation** first, to establish the starting number. With one
   prompt version there is nothing to compare against, so both columns show the
   same score - the UI says so explicitly rather than inventing a delta. Watch
   the `n / m` counter and elapsed timer as it runs.
3. Select a bug report → **Run LLM**. The structured output appears in an
   editable form, with the model's proposal shown underneath.
4. Change severity and/or component, adjust the rationale, and **Save
   correction**. Fields that differ from the model's answer are marked
   `changed`. Repeat for 8–12 reports - the more corrections, the more signal.
5. Click **Improve Prompt**. A new version (`v2-improved`) is generated from
   your corrections and becomes active. Use **View prompt text** to read exactly
   what was built and stored.
6. Click **Run Evaluation** again. The metrics panel now shows previous
   accuracy, current accuracy, the improvement delta, regression count, and the
   evaluation timestamp.

Corrections that *disagree* with the model teach the most, so a demo where you
deliberately fix the model's weak spots (under-called severities, everything
labelled `backend`) shows the largest, most legible gain.

---

## API reference

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness + which env vars are configured |
| `GET` | `/bugs` | List all bug reports |
| `POST` | `/bugs` | Create a bug report (`{"report_text": "..."}`) |
| `POST` | `/bugs/{bug_id}/run` | Classify with the active prompt |
| `PUT` | `/bugs/{bug_id}/correction` | Save a human correction + audit event |
| `GET` | `/prompts` | All prompt versions, oldest first |
| `GET` | `/prompts/active` | Active version + available correction count |
| `POST` | `/prompts/improve` | Build and activate a new version |
| `GET` | `/eval/examples` | The held-out gold set |
| `POST` | `/eval/run` | Score active vs previous version, store results, return comparison. `?force=true` re-scores the previous arm instead of reusing its stored run |
| `POST` | `/eval/run/stream` | Same work, streamed as newline-delimited JSON: `{"type":"progress","completed":n,"total":m,"arm":…}` per example, then one `{"type":"result"…}` or `{"type":"error"…}`. Also accepts `?force=true` |
| `GET` | `/eval/latest` | Last stored comparison (`204` if none yet) |

Errors are returned as `{"detail": "..."}`: `409` for an invalid state (no
corrections yet, no examples seeded), `502` for an upstream Supabase/OpenRouter
failure, `404` for a missing bug report.

---

## Tests

```bash
cd server && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest
```

42 tests covering the parts where correctness actually matters:

- **`test_grading.py`** - exact-match scoring, case/whitespace normalization,
  failed LLM calls counting as incorrect, per-axis accuracy, regression and
  improvement counting.
- **`test_prompt_service.py`** - few-shot selection prioritising disagreements,
  determinism, confusion tallies, prompt assembly, baseline pinning.
- **`test_evaluation_loop.py`** - the whole loop against an in-memory Supabase
  and a scripted model: both arms scored, a prompt that fixes two cases while
  breaking one reports **both** the gain and the regression, and `/eval/latest`
  reads back the same numbers from stored rows.

No test calls a real API, so the suite is fast (~0.1s) and free to run.

---

## Deployment

### Frontend → Cloudflare Pages

| Setting | Value |
| --- | --- |
| Build command | `npm run build` |
| Build output | `dist` |
| Root directory | `client` |
| Environment variable | `VITE_API_BASE_URL` = your deployed backend URL |

```bash
cd client && npm run build && npx wrangler pages deploy dist
```

Then set `CORS_ALLOW_ORIGINS` on the backend to your Pages URL.

### Database → Supabase

Free tier. Run `schema.sql` then `seed.sql`. Keep the service-role key in the
backend's secret store only.

### Backend → Cloudflare Workers (Python)

**Read this before choosing Workers.** Cloudflare's Python Workers run on
Pyodide, not CPython, and only a curated set of packages is available. FastAPI
and Pydantic are supported, but **`httpx` is not** - outbound HTTP from a Python
Worker goes through the JavaScript `fetch` binding.

This backend isolates all outbound HTTP in exactly two modules -
`app/db.py` and `app/llm.py` - precisely so that this swap is contained. Porting
means replacing the `httpx.AsyncClient` calls in those two files with the
Workers `fetch` binding; no route, service, or scoring code changes.

`wrangler.toml`:

```toml
name = "hitl-prompt-improvement"
main = "server/app/main.py"
compatibility_date = "2025-05-01"
compatibility_flags = ["python_workers"]
```

Set secrets with `wrangler secret put SUPABASE_URL` (and the other variables
from the table above) - never in `wrangler.toml`, which is committed.

**I have not deployed or verified the Workers path.** The application is
deliberately built to be portable rather than Workers-specific: because it is a
plain ASGI app whose only I/O is HTTP, it runs unmodified on any container host
(Fly.io, Render, Railway, Cloud Run):

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

That is the path I would take to production today, and I would revisit Workers
once the `httpx` shim above is written and tested.

---

## Assumptions

- **One reviewer at a time.** `reviewer_id` is a `localStorage` label used for
  attribution in the audit trail, not authentication. There is no login, and the
  API is unauthenticated.
- **Every correction is ground truth.** The system treats a saved correction as
  correct without adjudication, agreement scoring, or conflict resolution.
- **The comparison arm is the immediately previous version.** v3 is scored
  against v2, not against v1, so a delta answers "did the last improvement
  help?" rather than "how far have we come since the start". Cumulative
  progress against v1 is therefore not a reported number.
- **A previous version's score is stable enough to cache.** Its prompt text is
  immutable and decoding is deterministic (`temperature=0` + fixed seed), so a
  stored run is reused instead of recomputed. The cache is invalidated when the
  evaluation example set changes; a changed model or seed cannot be detected,
  which is what `?force=true` is for.
- **`v1-baseline` remains the composition root.** Improved versions are always
  rebuilt from it plus the full correction set, never by appending to the
  previous improved prompt. This is separate from the comparison arm.
- **The gold set is trustworthy and static.** Labels in `evaluation_examples`
  were written to be defensible, but they are my judgement calls; two reasonable
  engineers would disagree on a few. Bugs added through the UI join the review
  pool only - the evaluation set is never modified at runtime.
- **Exact label match is the right metric.** Severity is ordinal, so predicting
  `high` for a `critical` bug is scored exactly as wrong as predicting `low`.

## Limitations

- **The gold set is small (18 examples).** One example is worth ~5.6 percentage
  points, so small deltas are noise. Treat single-digit movements as
  inconclusive and read the regression count alongside the delta.
- **No statistical significance testing.** The UI reports a raw difference of
  proportions with no confidence interval.
- **Rationale quality is not scored.** It is stored and shown for manual
  inspection only. Scoring free text would require a second model, which this
  system deliberately avoids - accuracy must stay deterministic and auditable.
- **Evaluation cost grows linearly.** A run is one LLM call per example (18)
  when the previous arm is cached, and two per example (36) on a cache miss or
  with `?force=true`. Cheap on this model, but not free.
- **A cached previous score can go stale invisibly.** Changing
  `OPENROUTER_MODEL`, `LLM_TEMPERATURE` or `LLM_SEED` invalidates it in a way
  the code cannot detect, so the next comparison would mix decoding settings.
  Run once with `?force=true` after any such change.
- **Improvement is not guaranteed to be monotonic.** More corrections can make
  the prompt worse; that is exactly what the regression count is for. There is
  no automatic rollback - reactivating an older version is a manual DB update.
- **`POST /prompts/improve` is not concurrency-safe.** Two simultaneous calls
  could race between deactivating the old version and inserting the new one. The
  unique index prevents two active prompts from being committed, so the loser
  errors rather than corrupting state, but it is not retried.
- **Not verified against live Supabase or OpenRouter.** The loop was verified
  end to end over real HTTP against the real routes and services, with an
  in-memory database and a scripted model standing in for the two external
  services. Credentials were not available in the build environment.
