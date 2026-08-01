# Human-in-the-Loop Prompt Improvement System

**Production:** [frontend](https://hitl-pis.pages.dev/) · [docs](https://hitl-pis.pages.dev/docs) · [backend](https://hitl-prompt-improvement-api.kaarthickgokul.workers.dev/) · [health check](https://hitl-prompt-improvement-api.kaarthickgokul.workers.dev/health)

An LLM triages bug reports into structured JSON. A human reviewer corrects the
output. The corrections are stored, used to build a new prompt version, and a
deterministic evaluation proves whether the new prompt is actually better -
including whether it broke anything that used to work.

```
bug report ──> LLM triage ──> human correction ──> stored
                                                     │
                          ┌──────────────────────────┘
                          v
            candidate prompt (few-shot + calibration)
                          │
                          v
       fresh held-out evaluation: live prompt vs candidate
                          │
             positive gain + zero regressions?
                   activate / reject
```

**Stack:** React + Vite + Tailwind · FastAPI · Supabase Postgres · OpenRouter
(`deepseek/deepseek-v4-flash` by default).

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
4. **Improve** - "Build Candidate" creates a new prompt version from every stored
   correction but keeps the current prompt active. The generated text is stored in
   `prompt_versions`. A stable operating structure and decision process live in
   `prompt_service.py`; calibration rules and reference cases are generated
   deterministically from the current human corrections.
5. **Evaluate and gate** - "Evaluate Candidate" freshly scores the live prompt
   and candidate on the same held-out set. The candidate is activated atomically
   only when overall accuracy increases and regressions are zero; otherwise it is
   retained as rejected evidence and the live prompt is unchanged.

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
│   └── tests/                 56 unit + loop tests
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

### Upgrading an existing database

After pulling candidate-evaluation changes, run `supabase/schema.sql` again
before restarting the API. The file is idempotent and adds the prompt lifecycle
columns plus the transactional `resolve_prompt_candidate` function without
deleting reports, corrections, prompts, or evaluation history.

If the UI says **database upgrade required** or Postgres reports that
`prompt_versions.lifecycle_status` does not exist, the API is connected to the
old schema. Apply `supabase/schema.sql`, then reload the application.

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
| `OPENROUTER_MODEL` | no | `deepseek/deepseek-v4-flash` | Production model used for triage and evaluation. |
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
| `prompt_versions` | Every prompt plus candidate/active/rejected lifecycle and evaluation decision |
| `evaluation_examples` | Held-out gold set with expected labels |
| `evaluation_runs` | One row per prompt version per evaluation: accuracies + regression count |
| `evaluation_results` | Per-example detail backing each run |

Notable constraints:

- Severity and component vocabularies are enforced by `CHECK` constraints, so a
  bad label fails at write time instead of silently corrupting accuracy.
- A partial unique index (`prompt_versions_single_active`) makes "two active
  prompts at once" unrepresentable.
- A second partial unique index allows only one unevaluated candidate, and the
  `resolve_prompt_candidate` RPC activates or rejects it transactionally.
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
5. Click **Build Candidate**. A new version (`v2-improved`) is generated from
   your corrections but remains inactive.
6. Click **Evaluate Candidate**. The metrics panel shows live-versus-candidate
   accuracy, delta, regression count, and the activation decision. A positive
   gain with zero regressions activates the candidate; every other result keeps
   the current prompt live.

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
| `POST` | `/prompts/improve` | Build one inactive candidate version |
| `GET` | `/eval/examples` | The held-out gold set |
| `POST` | `/eval/run` | With a candidate: freshly score live vs candidate and atomically activate or reject it. Otherwise score the current active/previous comparison. |
| `POST` | `/eval/run/stream` | Same work, streamed as newline-delimited JSON: `{"type":"progress","completed":n,"total":m,"arm":…}` per example, then one `{"type":"result"…}` or `{"type":"error"…}`. Also accepts `?force=true` |
| `GET` | `/eval/latest` | Last stored comparison (`204` if none yet) |
| `POST` | `/admin/reset` | Transactional reset to the 93-report unreviewed baseline. Requires `{"confirmation":"RESET"}` |

Errors are returned as `{"detail": "..."}`: `409` for an invalid state (no
corrections yet, no examples seeded), `502` for an upstream Supabase/OpenRouter
failure, `404` for a missing bug report.

The production Worker applies Cloudflare-native per-visitor limits only to LLM
entry points: 120 individual report classifications per minute and three
evaluation starts per minute. The first threshold exceeds the complete
93-report demo run; the second contains evaluation fan-out without affecting a
normal interview flow. Rate-limited calls return `429` with `Retry-After: 60`.

### Resetting the public demo

The **reset demo** control restores the initial interview state transactionally:
93 seeded reports become unreviewed, manual reports and audit/evaluation history
are removed, improved prompts are deleted, and `v1-baseline` becomes active.
The 18 held-out evaluation examples are preserved.

Apply the latest `supabase/schema.sql` once to install the `reset_demo()` RPC.
The button opens a confirmation dialog and remains disabled until the user types
the exact literal `RESET`. The operation is intentionally unauthenticated for
the interview demo, so anyone with access to the public application can reset
its state.

---

## Tests

```bash
cd server && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest
```

56 tests covering the parts where correctness actually matters:

- **`test_grading.py`** - exact-match scoring, case/whitespace normalization,
  failed LLM calls counting as incorrect, per-axis accuracy, regression and
  improvement counting.
- **`test_prompt_service.py`** - few-shot selection prioritising disagreements,
  determinism, confusion tallies, prompt assembly, baseline pinning.
- **`test_evaluation_loop.py`** - the whole loop against an in-memory Supabase
  and a scripted model: both arms are scored fresh for a candidate, regressions
  reject activation, a safe gain activates atomically, and `/eval/latest` reads
  accepted or rejected evidence back from stored rows.
- **`test_config.py` / `test_cors.py`** - Cloudflare runtime bindings override
  settings safely, malformed optional values retain defaults, and deployed CORS
  origins are applied without exposing secrets to the frontend.

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

The backend has a verified Cloudflare Python Worker entrypoint. FastAPI,
Pydantic, and `httpx` are resolved against Cloudflare's Pyodide package index;
local Uvicorn development continues to use `server/requirements.txt`.

Prerequisites: free Cloudflare account, Node.js, and `uv`. From the repository
root:

```bash
uv sync
uv run pywrangler login
uv run pywrangler secret put SUPABASE_URL
uv run pywrangler secret put SUPABASE_SERVICE_ROLE_KEY
uv run pywrangler secret put OPENROUTER_API_KEY
uv run pywrangler deploy
```

Each `secret put` command prompts for the value and stores it encrypted in
Cloudflare. The required secret names are declared in `wrangler.jsonc`, so a
deployment fails clearly when one is missing. Do not add secret values to that
file.

After deployment, verify the URL printed by Wrangler:

```bash
curl https://hitl-prompt-improvement-api.<your-subdomain>.workers.dev/health
```

For the frontend deployment:

1. Set `VITE_API_BASE_URL` to that Worker URL.
2. Deploy `client/dist` to Cloudflare Pages using the command above.
3. Replace `https://YOUR-PROJECT.pages.dev` in `wrangler.jsonc` with the exact
   Pages URL, then run `uv run pywrangler deploy` once more to apply CORS.

For local Worker testing, create a git-ignored `.dev.vars` in the repository
root containing the same three secrets, then run:

```bash
uv run pywrangler dev
```

The free Workers plan is suitable for this exercise, but it is not unlimited:
100,000 requests/day, 50 external subrequests per request, 128 MB memory, and
10 ms CPU time per request. The 18-case two-arm evaluation is intentionally
below the 50-subrequest ceiling, but the CPU allowance is tight; if Cloudflare
returns error 1102 during evaluation, the production solution is a queued or
batched evaluation rather than increasing concurrency.

The default OpenRouter model is also free, but free accounts are limited to 50
model requests/day. A candidate decision deliberately uses 36 calls because both
arms are scored fresh; deployment safety takes priority over reusing a possibly
incompatible cached score.

---

## Assumptions

- **One reviewer at a time.** `reviewer_id` is a `localStorage` label used for
  attribution in the audit trail, not authentication. There is no login, and the
  API is unauthenticated.
- **Every correction is ground truth.** The system treats a saved correction as
  correct without adjudication, agreement scoring, or conflict resolution.
- **The candidate is compared with the current live version.** Both arms run
  fresh under the same model and decoding settings. Cumulative progress against
  v1 is not reported.
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
- **Evaluation cost grows linearly.** A candidate decision makes two calls per
  example (36 total for this gold set). Cheap on this model, but not free.
- **Improvement is not guaranteed to be monotonic.** More corrections can make
  a candidate worse. The gate rejects a non-positive delta or any regression,
  but there is not yet a manual rollback control for an already active version.
- **Only one candidate may wait for evaluation.** The partial unique index
  rejects concurrent candidate creation; the client must evaluate or reject the
  existing candidate before building another one.
- **Not verified against live Supabase or OpenRouter.** The loop was verified
  end to end over real HTTP against the real routes and services, with an
  in-memory database and a scripted model standing in for the two external
  services. Credentials were not available in the build environment.
