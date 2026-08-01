-- Human-in-the-Loop Prompt Improvement System
-- Supabase / Postgres schema
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f supabase/schema.sql
-- or paste into the Supabase SQL editor.
--
-- Notes:
--  * Label vocabularies are enforced with CHECK constraints so that bad labels
--    fail at write time instead of silently corrupting evaluation accuracy.
--  * RLS is enabled with no policies. The backend uses the service-role key,
--    which bypasses RLS; the browser never talks to Supabase directly. This
--    makes "anon key leaked" a non-event for these tables.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Shared label vocabulary
-- ---------------------------------------------------------------------------
-- severity:  critical | high | medium | low
-- component: frontend | backend | mobile | auth | payments | database
--            | infrastructure | unknown

-- ---------------------------------------------------------------------------
-- prompt_versions
-- ---------------------------------------------------------------------------
create table if not exists prompt_versions (
    id                              uuid primary key default gen_random_uuid(),
    version_name                    text        not null unique,
    prompt_text                     text        not null,
    is_active                       boolean     not null default false,
    created_from_corrections_count  integer     not null default 0,
    created_at                      timestamptz not null default now()
);

-- At most one active prompt version at a time.
create unique index if not exists prompt_versions_single_active
    on prompt_versions ((is_active)) where is_active;

create index if not exists prompt_versions_created_at_idx
    on prompt_versions (created_at);

-- ---------------------------------------------------------------------------
-- bug_reports
-- ---------------------------------------------------------------------------
create table if not exists bug_reports (
    id                   uuid primary key default gen_random_uuid(),
    report_text          text        not null,
    source               text        not null default 'seed'
                             check (source in ('seed', 'manual')),
    llm_output_json      jsonb,
    human_corrected_json jsonb,
    status               text        not null default 'new'
                             check (status in ('new', 'llm_run', 'reviewed')),
    prompt_version_used  uuid references prompt_versions (id) on delete set null,
    reviewer_id          text,
    created_at           timestamptz not null default now(),
    llm_run_at           timestamptz,
    reviewed_at          timestamptz,
    last_updated_at      timestamptz not null default now()
);

create index if not exists bug_reports_status_idx     on bug_reports (status);
create index if not exists bug_reports_created_at_idx on bug_reports (created_at);

-- ---------------------------------------------------------------------------
-- review_events  (append-only audit trail of human corrections)
-- ---------------------------------------------------------------------------
create table if not exists review_events (
    id              uuid primary key default gen_random_uuid(),
    bug_report_id   uuid not null references bug_reports (id) on delete cascade,
    old_output_json jsonb,
    new_output_json jsonb        not null,
    reviewer_id     text         not null,
    created_at      timestamptz  not null default now()
);

create index if not exists review_events_bug_report_id_idx
    on review_events (bug_report_id);

-- ---------------------------------------------------------------------------
-- evaluation_examples  (held-out gold set; never shown to the improver)
-- ---------------------------------------------------------------------------
create table if not exists evaluation_examples (
    id                 uuid primary key default gen_random_uuid(),
    report_text        text not null,
    expected_severity  text not null
                           check (expected_severity in
                                  ('critical', 'high', 'medium', 'low')),
    expected_component text not null
                           check (expected_component in
                                  ('frontend', 'backend', 'mobile', 'auth',
                                   'payments', 'database', 'infrastructure',
                                   'unknown')),
    expected_rationale text
);

-- ---------------------------------------------------------------------------
-- evaluation_runs
-- ---------------------------------------------------------------------------
create table if not exists evaluation_runs (
    id                 uuid primary key default gen_random_uuid(),
    prompt_version_id  uuid not null references prompt_versions (id)
                           on delete cascade,
    severity_accuracy  double precision not null,
    component_accuracy double precision not null,
    overall_accuracy   double precision not null,
    regression_count   integer          not null default 0,
    created_at         timestamptz      not null default now()
);

create index if not exists evaluation_runs_created_at_idx
    on evaluation_runs (created_at);
create index if not exists evaluation_runs_prompt_version_idx
    on evaluation_runs (prompt_version_id);

-- ---------------------------------------------------------------------------
-- evaluation_results  (per-example detail for one run)
-- ---------------------------------------------------------------------------
create table if not exists evaluation_results (
    id                    uuid primary key default gen_random_uuid(),
    evaluation_run_id     uuid not null references evaluation_runs (id)
                              on delete cascade,
    evaluation_example_id uuid not null references evaluation_examples (id)
                              on delete cascade,
    predicted_json        jsonb,
    expected_json         jsonb   not null,
    severity_correct      boolean not null,
    component_correct     boolean not null,
    both_correct          boolean not null
);

create index if not exists evaluation_results_run_idx
    on evaluation_results (evaluation_run_id);

-- ---------------------------------------------------------------------------
-- Row level security: deny-by-default, service role bypasses.
-- ---------------------------------------------------------------------------
alter table prompt_versions     enable row level security;
alter table bug_reports         enable row level security;
alter table review_events       enable row level security;
alter table evaluation_examples enable row level security;
alter table evaluation_runs     enable row level security;
alter table evaluation_results  enable row level security;
