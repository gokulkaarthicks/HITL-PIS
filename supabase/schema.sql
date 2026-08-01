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

-- Additive lifecycle migration for databases created before candidate gating.
alter table prompt_versions
    add column if not exists lifecycle_status text,
    add column if not exists evaluated_against_prompt_id uuid
        references prompt_versions (id) on delete set null,
    add column if not exists evaluation_decision text,
    add column if not exists evaluated_at timestamptz;

update prompt_versions
set lifecycle_status = case when is_active then 'active' else 'superseded' end
where lifecycle_status is null;

alter table prompt_versions
    alter column lifecycle_status set default 'candidate',
    alter column lifecycle_status set not null;

do $constraints$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'prompt_versions_lifecycle_status_check'
    ) then
        alter table prompt_versions
            add constraint prompt_versions_lifecycle_status_check
            check (lifecycle_status in
                   ('candidate', 'active', 'rejected', 'superseded'));
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'prompt_versions_evaluation_decision_check'
    ) then
        alter table prompt_versions
            add constraint prompt_versions_evaluation_decision_check
            check (evaluation_decision is null or evaluation_decision in
                   ('activated', 'rejected'));
    end if;
end
$constraints$;

-- At most one active prompt version at a time.
create unique index if not exists prompt_versions_single_active
    on prompt_versions ((is_active)) where is_active;

create unique index if not exists prompt_versions_single_candidate
    on prompt_versions ((lifecycle_status)) where lifecycle_status = 'candidate';

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

-- ---------------------------------------------------------------------------
-- Demo reset RPC
--
-- Restores the seeded review workflow without touching the held-out gold set.
-- One Postgres function keeps the destructive operation transactional.
-- ---------------------------------------------------------------------------
create or replace function public.reset_demo()
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    baseline_id uuid;
    deleted_manual_count integer;
    seeded_bug_count integer;
begin
    select id into baseline_id
    from prompt_versions
    where version_name = 'v1-baseline';

    if baseline_id is null then
        raise exception 'Cannot reset: v1-baseline does not exist';
    end if;

    -- Keep an explicit predicate so this works when Supabase's safe-update
    -- guard rejects full-table DELETE statements without a WHERE clause.
    delete from evaluation_runs where true;
    delete from review_events where true;

    delete from bug_reports where source = 'manual';
    get diagnostics deleted_manual_count = row_count;

    update bug_reports
    set llm_output_json = null,
        human_corrected_json = null,
        status = 'new',
        prompt_version_used = null,
        reviewer_id = null,
        llm_run_at = null,
        reviewed_at = null,
        last_updated_at = now()
    where source = 'seed';

    update prompt_versions set is_active = false where is_active;
    delete from prompt_versions where id <> baseline_id;
    update prompt_versions
    set is_active = true,
        lifecycle_status = 'active',
        evaluated_against_prompt_id = null,
        evaluation_decision = null,
        evaluated_at = null,
        created_from_corrections_count = 0
    where id = baseline_id;

    select count(*) into seeded_bug_count
    from bug_reports
    where source = 'seed';

    return jsonb_build_object(
        'status', 'reset',
        'seeded_bug_count', seeded_bug_count,
        'deleted_manual_count', deleted_manual_count,
        'active_prompt', 'v1-baseline'
    );
end;
$$;

revoke all on function public.reset_demo() from public, anon, authenticated;
grant execute on function public.reset_demo() to service_role;

-- Resolve a held-out evaluation as one transaction. A candidate can become
-- active only when the application has already verified a positive delta and
-- zero regressions; otherwise it is retained as rejected evidence.
create or replace function public.resolve_prompt_candidate(
    p_candidate_id uuid,
    p_evaluated_against_prompt_id uuid,
    p_accept boolean
)
returns setof prompt_versions
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if not exists (
        select 1 from prompt_versions
        where id = p_candidate_id
          and lifecycle_status = 'candidate'
          and not is_active
    ) then
        raise exception 'Candidate prompt is missing or already resolved';
    end if;

    if not exists (
        select 1 from prompt_versions
        where id = p_evaluated_against_prompt_id
          and is_active
    ) then
        raise exception 'Evaluation control is no longer the active prompt';
    end if;

    if p_accept then
        update prompt_versions
        set is_active = false,
            lifecycle_status = 'superseded'
        where id = p_evaluated_against_prompt_id;

        update prompt_versions
        set is_active = true,
            lifecycle_status = 'active',
            evaluated_against_prompt_id = p_evaluated_against_prompt_id,
            evaluation_decision = 'activated',
            evaluated_at = now()
        where id = p_candidate_id;
    else
        update prompt_versions
        set lifecycle_status = 'rejected',
            evaluated_against_prompt_id = p_evaluated_against_prompt_id,
            evaluation_decision = 'rejected',
            evaluated_at = now()
        where id = p_candidate_id;
    end if;

    return query select * from prompt_versions where id = p_candidate_id;
end;
$$;

revoke all on function public.resolve_prompt_candidate(uuid, uuid, boolean)
    from public, anon, authenticated;
grant execute on function public.resolve_prompt_candidate(uuid, uuid, boolean)
    to service_role;
