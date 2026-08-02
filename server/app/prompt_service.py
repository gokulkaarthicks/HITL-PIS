"""Prompt versioning and deterministic prompt assembly.

An improved prompt is always composed as: baseline core + calibration learned
from human corrections. It is rebuilt from the *baseline* each time rather than
by appending to the current active prompt, so repeated improvements converge on
the correction set instead of accumulating layers of stale guidance.

The generated text is stored in `prompt_versions`. Stable operating guidance
is combined with correction-derived calibration and representative examples;
no model is asked to rewrite or summarize another model's prompt.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .db import SupabaseClient, SupabaseError
from .grading import normalize_label

BASELINE_VERSION_NAME = "v1-baseline"

DECISION_PROCESS = """## Decision process

1. Use only evidence stated in the report; do not invent missing impact or scope.
2. Choose severity from user impact, breadth, urgency, security/data risk, and
   whether a practical workaround exists.
3. Choose the component that owns the likely root cause, not merely the screen
   where the symptom appears. Use `unknown` when the report is too vague.
4. Give a concise rationale that cites the evidence driving both labels."""

Row = dict[str, Any]


class PromptServiceError(RuntimeError):
    """Raised when prompt state is inconsistent or improvement is not possible."""


def is_candidate_schema_missing(exc: SupabaseError) -> bool:
    """Recognize PostgREST errors from databases that predate candidate gating."""
    detail = exc.detail.lower()
    return "lifecycle_status" in detail and (
        "does not exist" in detail or "schema cache" in detail
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def list_prompts(db: SupabaseClient) -> list[Row]:
    return await db.select("prompt_versions", order="created_at.asc")


async def get_active_prompt(db: SupabaseClient) -> Row:
    row = await db.select_one("prompt_versions", filters={"is_active": "is.true"})
    if row is None:
        raise PromptServiceError(
            "No active prompt version. Did you run supabase/seed.sql?"
        )
    return row


async def get_candidate_prompt(db: SupabaseClient) -> Row | None:
    """Return the single prompt waiting for evaluation, if one exists."""
    try:
        return await db.select_one(
            "prompt_versions", filters={"lifecycle_status": "eq.candidate"}
        )
    except SupabaseError as exc:
        if is_candidate_schema_missing(exc):
            raise PromptServiceError(
                "Database upgrade required: apply supabase/schema.sql before "
                "using candidate prompt evaluation."
            ) from exc
        raise


async def get_baseline_prompt(db: SupabaseClient) -> Row:
    """The composition root every improved prompt is rebuilt from.

    This is *not* the evaluation control arm (see `get_previous_prompt`). It is
    the stable core text that `improve_prompt` layers calibration onto, which is
    what stops repeated improvements from accumulating stale guidance.

    Resolved by name rather than by "oldest row": timestamp ordering is a weak
    guarantee (ties, clock skew, or a backfilled row all silently move it).
    Falls back to the oldest version only if the seeded baseline is absent.
    """
    named = await db.select_one(
        "prompt_versions", filters={"version_name": f"eq.{BASELINE_VERSION_NAME}"}
    )
    if named is not None:
        return named

    rows = await db.select("prompt_versions", order="created_at.asc", limit=1)
    if not rows:
        raise PromptServiceError(
            "No prompt versions exist. Did you run supabase/seed.sql?"
        )
    return rows[0]


async def get_previous_prompt(db: SupabaseClient, active: Row) -> Row | None:
    """The version created immediately before `active` -- the evaluation control.

    Comparing against the previous version answers the operational question
    ("did the last improvement help, and did it break anything that worked?")
    rather than "how far have we come since v1".

    `version_name` is a deterministic tiebreak on `created_at`. Ordering on
    timestamp alone is exactly the fragility that once let the wrong prompt slip
    into the control slot, so it is not relied on by itself.

    Returns None when `active` is the oldest version -- a fresh install with
    nothing to compare against yet.
    """
    rows = await db.select(
        "prompt_versions",
        order="created_at.desc,version_name.desc",
    )
    active_created_at = str(active.get("created_at") or "")
    for row in rows:
        if row["id"] == active["id"]:
            continue
        if str(row.get("created_at") or "") < active_created_at:
            return row
    return None


# ---------------------------------------------------------------------------
# Improvement
# ---------------------------------------------------------------------------
def _label_pair(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "", ""
    return normalize_label(payload.get("severity")), normalize_label(
        payload.get("component")
    )


def _correction_sort_key(row: Row) -> tuple[str, str]:
    return (
        str(row.get("reviewed_at") or row.get("last_updated_at") or ""),
        str(row.get("id") or ""),
    )


def _has_explanatory_rationale(row: Row) -> bool:
    payload = row.get("human_corrected_json")
    if not isinstance(payload, dict):
        return False
    # A worked example should explain the decision, not teach placeholders such
    # as "x" or "ok". Labels still contribute to aggregate calibration below.
    return len(str(payload.get("rationale") or "").strip()) >= 20


def _teaching_signal_sort_key(row: Row) -> tuple[int, int, tuple[str, str]]:
    """Rank corrections by how much verified human judgment they add."""
    original = _label_pair(row.get("llm_output_json"))
    corrected = _label_pair(row.get("human_corrected_json"))
    changed_axes = sum(before != after for before, after in zip(original, corrected))
    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    severity_distance = abs(
        severity_order.get(original[0], 0) - severity_order.get(corrected[0], 0)
    )
    return -changed_axes, -severity_distance, _correction_sort_key(row)


def group_reference_corrections(
    corrections: list[Row],
) -> list[tuple[Row, list[Row]]]:
    """Group every useful disagreement by its verified label outcome.

    Only corrections where the human changed the model are eligible. They are
    ranked by changed axes and severity distance. The strongest correction for
    each corrected severity/component pair becomes the primary example; every
    additional correction for that same pair becomes a related nuance.

    Rows without an explanatory rationale still influence aggregate calibration
    but are not suitable as reference evidence.

    Ordering is deterministic so the same correction set always produces
    byte-identical prompt text.
    """
    disagreements: list[Row] = []

    for row in sorted(corrections, key=_correction_sort_key):
        original = _label_pair(row.get("llm_output_json"))
        corrected = _label_pair(row.get("human_corrected_json"))
        if not all(corrected) or not _has_explanatory_rationale(row):
            continue
        if original != corrected:
            disagreements.append(row)

    grouped: dict[tuple[str, str], list[Row]] = {}
    for row in sorted(disagreements, key=_teaching_signal_sort_key):
        grouped.setdefault(_label_pair(row.get("human_corrected_json")), []).append(
            row
        )

    groups = [(rows[0], rows[1:]) for rows in grouped.values()]
    return sorted(groups, key=lambda group: _teaching_signal_sort_key(group[0]))


def summarize_confusions(corrections: list[Row]) -> tuple[list[str], list[str]]:
    """Count how the model's labels were changed, per axis.

    Returns human-readable lines, most frequent first. Purely a tally of stored
    data -- no model, no inference.
    """
    severity_changes: Counter[tuple[str, str]] = Counter()
    component_changes: Counter[tuple[str, str]] = Counter()

    for row in corrections:
        was_sev, was_comp = _label_pair(row.get("llm_output_json"))
        now_sev, now_comp = _label_pair(row.get("human_corrected_json"))
        if was_sev and now_sev and was_sev != now_sev:
            severity_changes[(was_sev, now_sev)] += 1
        if was_comp and now_comp and was_comp != now_comp:
            component_changes[(was_comp, now_comp)] += 1

    def render(counter: Counter[tuple[str, str]]) -> list[str]:
        return [
            f"- Prefer `{now}` over `{was}` in matching cases "
            f"({count} reviewed {'correction' if count == 1 else 'corrections'})."
            for (was, now), count in sorted(
                counter.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]

    return render(severity_changes), render(component_changes)


def _compact(value: object, limit: int) -> str:
    """Collapse whitespace and bound one embedded evidence fragment."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_improved_prompt_text(baseline_text: str, corrections: list[Row]) -> str:
    """Compose a concise operating prompt. Pure and deterministic."""
    reference_groups = group_reference_corrections(corrections)
    severity_lines, component_lines = summarize_confusions(corrections)

    sections: list[str] = [
        "# Bug report triage operating prompt\n\n"
        "## Role, task, and output contract\n\n" + baseline_text.strip(),
        DECISION_PROCESS,
    ]

    guidance: list[str] = []
    if severity_lines:
        guidance.append("### Severity calibration\n" + "\n".join(severity_lines))
    if component_lines:
        guidance.append("### Component calibration\n" + "\n".join(component_lines))

    if guidance:
        sections.append(
            "## Calibration from human review\n\n"
            f"This is a deduplicated summary of label changes across "
            f"{len(corrections)} verified reports. Apply a preference only "
            "when the new report has matching evidence.\n\n" + "\n\n".join(guidance)
        )

    if reference_groups:
        rendered = []
        for index, (row, nuances) in enumerate(reference_groups, start=1):
            corrected = row.get("human_corrected_json") or {}
            report_text = str(row.get("report_text", "")).strip()
            example = (
                f"### Example {index}\n\nReport:\n{report_text}\n\n"
                "Verified classification:\n"
                + json.dumps(
                    {
                        "severity": normalize_label(corrected.get("severity")),
                        "component": normalize_label(corrected.get("component")),
                        "rationale": str(corrected.get("rationale", "")).strip()[:300],
                    },
                    indent=2,
                )
            )
            if nuances:
                nuance_lines = []
                for nuance in nuances:
                    payload = nuance.get("human_corrected_json") or {}
                    nuance_lines.append(
                        f"- {_compact(nuance.get('report_text'), 240)} "
                        f"Reasoning nuance: {_compact(payload.get('rationale'), 180)}"
                    )
                example += (
                    "\n\nRelated reviewed nuances with the same verified labels:\n"
                    + "\n".join(nuance_lines)
                )
            rendered.append(example)
        sections.append(
            "## Distinctive human-verified reference cases\n\n"
            "Every distinct corrected severity/component outcome has one primary "
            "example. Additional reviews with the same outcome appear as nuances "
            "instead of duplicate examples. They are evidence, not universal "
            "rules; match their reasoning only when impact and ownership are "
            "comparable.\n\n" + "\n\n".join(rendered)
        )

    sections.append(
        "## Final instruction\n\n"
        "Classify the incoming report independently using the contract, decision "
        "process, calibration evidence, and closest relevant examples above."
    )
    return "\n\n".join(sections)


def next_version_name(existing: list[Row]) -> str:
    return f"v{len(existing) + 1}-improved"


async def fetch_corrections(db: SupabaseClient) -> list[Row]:
    """All human-reviewed bug reports, which are the training signal."""
    return await db.select(
        "bug_reports",
        columns="id,report_text,llm_output_json,human_corrected_json,"
        "reviewed_at,last_updated_at",
        filters={"status": "eq.reviewed"},
        order="reviewed_at.asc",
    )


async def improve_prompt(db: SupabaseClient) -> Row:
    """Create an inactive candidate prompt from stored corrections.

    The candidate must pass held-out evaluation before it can become active.
    Keeping the current prompt live closes the unsafe window where an untested
    prompt previously served production traffic.
    """
    if await get_candidate_prompt(db) is not None:
        raise PromptServiceError(
            "A candidate prompt is already waiting for evaluation. Run the "
            "evaluation before creating another candidate."
        )
    corrections = await fetch_corrections(db)
    usable = [
        row for row in corrections if all(_label_pair(row.get("human_corrected_json")))
    ]
    if not usable:
        raise PromptServiceError(
            "No human corrections saved yet. Review at least one bug report "
            "before improving the prompt."
        )

    baseline = await get_baseline_prompt(db)
    existing = await list_prompts(db)

    prompt_text = build_improved_prompt_text(baseline["prompt_text"], usable)

    created = await db.insert(
        "prompt_versions",
        {
            "version_name": next_version_name(existing),
            "prompt_text": prompt_text,
            "is_active": False,
            "lifecycle_status": "candidate",
            "created_from_corrections_count": len(usable),
        },
    )
    if not created:
        raise PromptServiceError("Failed to create the candidate prompt version.")
    return created[0]


async def resolve_candidate(
    db: SupabaseClient,
    candidate_id: str,
    evaluated_against_prompt_id: str,
    *,
    accept: bool,
) -> Row:
    """Atomically activate or reject a candidate after evaluation."""
    rows = await db.rpc(
        "resolve_prompt_candidate",
        {
            "p_candidate_id": candidate_id,
            "p_evaluated_against_prompt_id": evaluated_against_prompt_id,
            "p_accept": accept,
        },
    )
    if not rows:
        raise PromptServiceError("Failed to resolve the evaluated candidate prompt.")
    return rows[0]
