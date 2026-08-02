# Design

Design notes for the Human-in-the-Loop Prompt Improvement System: how it is put
together, why the prompt-improvement and evaluation methods are what they are,
what was traded away, and what would need to change for production.

---

## 1. Architecture

```
┌──────────────────────┐        ┌──────────────────────────────┐
│  React + Vite + TW   │        │          FastAPI             │
│  (Cloudflare Pages)  │──HTTP─>│    (Workers / container)     │
│                      │        │                              │
│  three-pane UI       │        │  routes/  thin HTTP layer    │
│  no credentials      │        │  services prompt · eval      │
└──────────────────────┘        │  grading.py  pure functions  │
                                └────────┬──────────┬──────────┘
                                         │          │
                                  PostgREST      HTTPS
                                         │          │
                                 ┌───────v──┐  ┌────v────────┐
                                 │ Supabase │  │ OpenRouter  │
                                 │ Postgres │  │  deepseek   │
                                 └──────────┘  └─────────────┘
```

### Layering

Four layers, one direction of dependency:

| Layer | Files | Responsibility |
| --- | --- | --- |
| Routes | `routes/*.py` | HTTP shape only: parse, delegate, return |
| Services | `prompt_service.py`, `evaluation.py` | Orchestration and business rules |
| Pure logic | `grading.py`, prompt assembly | Deterministic, no I/O, unit tested |
| I/O clients | `db.py`, `llm.py` | The only modules that touch the network |

The layer that decides *what is correct* (`grading.py`) has no I/O at all. That
is what makes the metrics auditable: scoring can be verified by reading one
short file and running its tests, with no database or API key.

### Why the frontend never holds a credential

Supabase and OpenRouter are reached only from the backend. The browser bundle
holds one value, `VITE_API_BASE_URL`, which is public by construction. Anything
`VITE_`-prefixed is inlined into the JavaScript, so treating that boundary
strictly is the difference between a leaked service-role key and a leaked URL.

### Why PostgREST instead of a Postgres driver

The stated deployment target is Cloudflare Workers, which cannot open raw TCP
sockets - so `asyncpg` and `psycopg` are unavailable there regardless of how the
code is written. Supabase exposes PostgREST over HTTPS, which works identically
on Workers, on a container, and locally.

The cost is real and worth naming: **no transactions**. Each PostgREST call is
its own statement, so a multi-step write cannot be made atomic from application
code. Section 5 covers where this actually bites.

`db.py` implements only the four verbs the app uses, with PostgREST operator
strings (`{"id": "eq.<uuid>"}`) passed explicitly by callers. An unsupported
filter form raises rather than silently matching everything.

### Schema decisions

- **`CHECK` constraints for label vocabularies.** An invalid label is rejected
  at write time. Accuracy is computed by string equality, so a stray
  `"Critical"` or `"payment"` would quietly depress every subsequent score.
- **Partial unique indexes for active and candidate prompts.** The database can
  hold at most one live prompt and one candidate waiting for evaluation.
- **Transactional candidate resolution.** `resolve_prompt_candidate` verifies
  that the evaluation control is still live, then activates or rejects the
  candidate in one database transaction.
- **RLS on, zero policies.** The service-role key bypasses RLS; nothing else
  reaches these tables. Should an anon key ever be exposed, it grants nothing.
- **`review_events` is append-only.** `bug_reports` holds current state;
  `review_events` holds history. Keeping them separate means a reviewer changing
  their mind twice leaves three readable rows instead of one overwritten cell.

---

## 2. Prompt improvement approach

### What gets built

An improved prompt is assembled from five explicit sections:

1. **Role, task, and output contract** - the baseline core, verbatim.
2. **A decision process** - evidence-only classification, impact-based severity,
   root-cause component ownership, and concise rationale guidance.
3. **A calibration section** - a deduplicated tally of how reviewers changed the model's
   labels, most frequent first:
   `- Prefer critical over high in matching cases (3 reviewed corrections).`
4. **Distinctive reference cases** - one primary example for every corrected
   label pair, with additional corrections for that outcome folded into concise
   reasoning nuances instead of repeated full examples.
5. **A final execution instruction** - apply the evidence to the incoming report
   independently rather than copying an example mechanically.

The assembled text is written to `prompt_versions.prompt_text` as an inactive
candidate. It becomes active only after a positive held-out gain with zero
regressions.
`build_improved_prompt_text` is a pure, deterministic function over correction
rows. Stable operating guidance is code; learned calibration and examples come
only from stored human review.

### Which corrections become examples

Only corrections where the human **disagreed** with the model become reference
cases. That is where the teaching signal is: a case the model already got right
demonstrates nothing it does not already do. Confirmations remain represented
by the core contract rather than consuming prompt space.

Selection ranks changes to both axes and large severity corrections first, then
keeps at most one case per corrected severity/component pair. It never fills
remaining space with repeated outcomes. Placeholder rationales are excluded
from reference cases, though their labels still affect calibration counts. A
stable id tiebreak keeps the same correction set byte-identical. That matters more than it sounds:
if prompt generation were unstable, a re-run could change accuracy and there
would be no way to attribute the difference.

### Why rebuild from the baseline every time

Each improvement is `baseline + all corrections to date`, never
`previous_improved + new corrections`. Appending would compound: round five
would carry four layers of stale calibration, some of it contradicting later
review decisions, and the prompt would grow without bound. Rebuilding means the
prompt is always a clean function of the current correction set, and an early
mistaken correction can be undone simply by fixing it and improving again.

### Why few-shot rather than fine-tuning or meta-prompting

- **Fine-tuning** needs far more than a few dozen labels, costs a training
  round-trip per iteration, and makes the improvement opaque - you cannot read a
  weight diff and see what the reviewer taught.
- **Asking an LLM to rewrite the prompt** ("meta-prompting") is the other
  obvious option. It was rejected because it makes the system's central claim
  unfalsifiable: if a model writes the prompt *and* a model produces the labels,
  an improvement is hard to attribute and impossible to audit. The current
  approach is fully inspectable - "View prompt text" shows exactly what was
  built and every line traces to a stored correction.
- **Few-shot from corrections** is legible, cheap, immediate, and reversible.

The honest limitation: few-shot prompting plateaus. Past roughly 15–20 examples,
added examples mostly consume context. Section 6 covers what replaces it.

---

## 3. Evaluation method

### Deterministic scoring, by construction

A prediction is correct when its normalized label string equals the expected
label string. That is the whole rule. `normalize_label` trims and lowercases so
cosmetic differences never register as errors.

**No model judges accuracy.** `grading.py` imports nothing but the label types.
This is a deliberate constraint rather than a simplification: an LLM judge would
add a second stochastic component to the exact measurement meant to prove the
first one improved, and any delta would then be inseparable from judge drift.

### Two arms, one variable

Every candidate decision freshly scores the same held-out examples under the
live prompt and candidate, with identical decoding settings (`temperature=0`,
fixed `seed`, same model). The prompt text is the only variable, which licenses
attributing the delta to the candidate.

The control is the current live version rather than a fixed `v1-baseline` because
the operationally useful question is "did the last improvement help, and did it
break anything that worked last round?" - the same question a CI check asks of a
diff. Comparing every round against v1 answers "how far have we come", which
flatters late rounds and hides a round that made things worse.

Selecting "previous" is ordering-sensitive, and ordering is exactly what has
bitten this code before: an earlier version resolved the control arm by
`created_at` alone, and a fixture whose clock ran behind the seeded row promoted
the *improved* prompt into the control slot - reporting a truthful-looking 0.0%
delta while comparing a prompt against itself. The same fixture clock later
backdated inserted versions and made "previous" resolve to nothing at all. So
`get_previous_prompt` orders by `created_at desc, version_name desc` - a
deterministic tiebreak - takes the first row strictly older than the active one,
and is covered by tests for the ordinary case, the oldest-version case, and the
case where a newer version exists but must be ignored.

Note this is *not* the same thing as `get_baseline_prompt`, which still resolves
`v1-baseline` by name. That one is the composition root every improved prompt is
rebuilt from (§2); it no longer has anything to do with the comparison arm.

### Candidate deployment gate

Candidate decisions never reuse a cached control arm. Both prompts are scored
in the same run so a model, seed, or decoding change cannot be mistaken for a
prompt improvement. The candidate is promoted only when overall accuracy is
strictly higher and the regression count is zero. Otherwise it is retained with
status `rejected`, and the live prompt remains unchanged.

The final state transition is a Postgres RPC. It checks that the candidate is
still pending and that the evaluated control is still active before changing
either row, preventing concurrent requests from promoting stale work.

### Metrics, and why regressions are reported separately

| Metric | Definition |
| --- | --- |
| `severity_accuracy` | Fraction with correct severity |
| `component_accuracy` | Fraction with correct component |
| `overall_accuracy` | Fraction with **both** correct |
| `regression_count` | Examples the baseline got fully right that the active prompt gets wrong |
| `improved_count` | Examples the baseline got wrong that the active prompt gets fully right |

`overall_accuracy` requires both axes because a triage that is right about
severity and wrong about component routes the ticket to the wrong team - a mean
of two independent accuracies would hide that.

Regression count is the guardrail. A prompt can raise average accuracy while
destroying cases that previously worked, and averaging makes that invisible.
Reporting both means "+8 points, 3 regressions" reads as the genuinely mixed
result it is, instead of a win.

### Failure handling

A failed or unparseable LLM call scores as **incorrect**, not skipped. Skipping
would let a prompt that reliably produces malformed output post a high score on
whatever fraction survived. The run continues so a transient blip does not
discard an entire evaluation.

### Reproducibility

`temperature=0` plus a fixed seed plus JSON-schema-constrained output means a
re-run on unchanged data should reproduce its labels. This is best-effort -
providers do not guarantee determinism - but it removes sampling noise as the
first explanation for a moved number.

### Why rationale is not scored

Rationale is stored, displayed, and left to human judgement. Scoring it needs
either a second model (rejected above) or string overlap against a reference,
which rewards paraphrase rather than reasoning. The field is labelled
"not scored - reviewed manually" in the UI so the boundary is visible to the
reviewer rather than buried here.

---

## 4. Frontend design

Three panes matching the three phases of the loop: **select** (left),
**triage and correct** (centre), **improve and measure** (right). Server state
lives in `App.jsx` and flows down; there is no state library because there is
one screen and roughly six pieces of state.

Two decisions worth noting:

- **Empty states are treated as first-class.** Every one of "no LLM run yet",
  "no correction saved yet", "no previous evaluation", "no improved prompt yet"
  is an explicit component with an instruction, not a blank div. A reviewer
  should always know what to do next.
- **The UI never fabricates a comparison.** With only the baseline existing,
  both metric columns show the same number and the panel says so in words.
  Showing a `+0.0%` delta without explanation would imply a comparison that did
  not happen.

The form seeds from the saved correction when one exists, otherwise from the raw
LLM output, and marks fields that differ from the model's proposal as `changed`
- so a reviewer can see their own edits at a glance before saving.

---

## 5. Tradeoffs

| Decision | Gained | Gave up |
| --- | --- | --- |
| PostgREST over a Postgres driver | Runs on Workers; identical everywhere | **Transactions**; multi-step writes are not atomic |
| Exact label match | Auditable, deterministic, trivial to verify | No partial credit; ordinal severity treated as categorical |
| Few-shot from corrections | Legible, cheap, immediate, reversible | Plateaus; context grows with example count |
| Rebuild from baseline each time | No drift; prompt is a clean function of corrections | Cannot hand-tune an improved prompt and keep it |
| Live version as candidate control | Tests exactly what would change at deployment | Deltas do not show cumulative progress against v1 |
| Fresh candidate arms | Comparable evidence and safe activation | Doubles candidate evaluation calls |
| 18 held-out examples | Fast, cheap runs | ±5.6 points per example; small deltas are noise |
| No auth | Zero friction for a single-reviewer demo | Unsuitable for real multi-user deployment |
| Corrections are ground truth | Simple, no adjudication UI | One careless reviewer poisons every later prompt |

Prompt creation remains a cheap PostgREST insert, while the safety-critical
activation is a transactional RPC. This keeps the live prompt unchanged if
evaluation, persistence, or candidate resolution fails.

---

## 6. What production would need

Ordered by what I would do first.

**1. Authentication and real reviewer identity.** Supabase Auth, with
`reviewer_id` becoming a real foreign key and RLS policies replacing the
service-role key for user-scoped reads. The current `localStorage` id is an
attribution label and nothing more; it must not be mistaken for a security
boundary.

**2. A larger, versioned gold set.** 18 examples cannot resolve small effects.
I would target 150–300 examples, labelled by more than one person with
inter-annotator agreement tracked, and version the set so a change to the
examples is never confused with a change to the prompt. With that in place,
report confidence intervals and gate on statistical significance rather than raw
deltas.

**3. Richer deployment policy and rollback.** Keep one-click rollback to any
earlier version and, with a larger gold set, require statistical significance in
addition to the current positive-delta and zero-regression gate.

**4. Background evaluation runs.** At 300 examples an evaluation is 600 LLM
calls, well past an HTTP request's lifetime. Queue the run, stream progress, and
persist partial results.

**5. Correction quality controls.** Inter-reviewer agreement, double-review for
disagreements, and the ability to exclude a correction from prompt building
without deleting the audit record. Today one careless reviewer silently degrades
every subsequent prompt.

**6. Ordinal-aware severity metrics.** Adjacent-error weighting or Cohen's
kappa, reported alongside exact match - `high` for `critical` is a materially
better mistake than `low` for `critical`, and the current metric cannot say so.

**7. Operational basics.** Structured request logging with correlation ids,
per-run token and cost tracking, retry with backoff on 429s (which currently
score as incorrect and understate a prompt's true accuracy), and alerting on
regression count.

**8. Beyond few-shot.** Once examples plateau, the next step is retrieval -
select the *k* most similar corrections per report rather than a fixed global
set - and only then consider fine-tuning, with this evaluation harness as the
thing that proves it was worth it.
