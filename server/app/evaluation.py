"""Held-out evaluation and candidate deployment gating.

Candidate decisions score the candidate against a fingerprinted live-prompt
control over the same `evaluation_examples`. The control is reused only while
the effective prompt, model settings, output schema, and held-out set match.
Promotion uses deterministic exact-match metrics and explicit guardrails.

When no candidate exists, the legacy active-versus-previous comparison remains
available and may reuse a stored previous arm. Scoring itself is deterministic
pure Python in `grading.py`; no model judges accuracy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .config import settings
from .db import SupabaseClient
from .grading import (
    Accuracy,
    ExampleGrade,
    aggregate,
    count_improvements,
    count_regressions,
    grade_example,
)
from .http_client import AsyncHTTPClient
from .llm import LLMError, TRIAGE_JSON_SCHEMA, build_system_prompt, classify
from .prompt_service import (
    get_active_prompt,
    get_candidate_prompt,
    get_previous_prompt,
    list_prompts,
    resolve_candidate,
)
from .schemas import EvalComparison, EvalRunSummary, RegressionDetail, Triage

Row = dict[str, Any]

# Called once per completed example so callers can stream progress.
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class EvaluationError(RuntimeError):
    """Raised when an evaluation cannot be run at all."""


MIN_REMAINING_ERROR_REDUCTION = 0.30
MAX_ORDINARY_REGRESSIONS = 2
MAX_CLASSIFICATION_ATTEMPTS = 2
PROTECTED_SEVERITIES = {"critical"}
TOLERATED_PROTECTED_SEVERITIES = {"critical", "high"}
EVALUATION_CACHE_VERSION = 1


# ---------------------------------------------------------------------------
# Scoring one arm
# ---------------------------------------------------------------------------
class _Progress:
    """Counts completed examples and forwards them to an optional callback."""

    def __init__(self, total: int, callback: ProgressCallback | None) -> None:
        self.total = total
        self.completed = 0
        self._callback = callback

    async def tick(self, arm: str) -> None:
        self.completed += 1
        if self._callback is not None:
            await self._callback(
                {
                    "type": "progress",
                    "completed": self.completed,
                    "total": self.total,
                    "arm": arm,
                }
            )


async def _predict_all(
    llm_client: AsyncHTTPClient,
    examples: list[Row],
    prompt_text: str,
    *,
    semaphore: asyncio.Semaphore,
    arm: str,
    progress: _Progress | None = None,
) -> list[ExampleGrade]:
    """Classify every example under one prompt and grade the results.

    The semaphore is passed in rather than created here so that concurrency is
    bounded across *both* arms. Creating it per arm would silently double the
    configured fan-out whenever two arms run.
    """

    async def one(example: Row) -> ExampleGrade:
        async with semaphore:
            predicted: Triage | None = None
            for _attempt in range(MAX_CLASSIFICATION_ATTEMPTS):
                try:
                    predicted = await classify(
                        llm_client, example["report_text"], prompt_text
                    )
                    break
                except LLMError:
                    # Retry once because a transient provider failure must not
                    # manufacture a regression. Persistent failures still score
                    # as incorrect so an unreliable prompt cannot be promoted.
                    continue
        grade = grade_example(
            example_id=example["id"],
            predicted=predicted,
            expected_severity=example["expected_severity"],
            expected_component=example["expected_component"],
        )
        if progress is not None:
            await progress.tick(arm)
        return grade

    return await asyncio.gather(*(one(e) for e in examples))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
async def _store_run(
    db: SupabaseClient,
    prompt_version_id: str,
    grades: list[ExampleGrade],
    accuracy: Accuracy,
    regression_count: int,
    cache_fingerprint: str,
) -> Row:
    created = await db.insert(
        "evaluation_runs",
        {
            "prompt_version_id": prompt_version_id,
            "severity_accuracy": accuracy.severity_accuracy,
            "component_accuracy": accuracy.component_accuracy,
            "overall_accuracy": accuracy.overall_accuracy,
            "regression_count": regression_count,
            "cache_fingerprint": cache_fingerprint,
        },
    )
    if not created:
        raise EvaluationError("Failed to persist the evaluation run.")
    run = created[0]

    if grades:
        await db.insert(
            "evaluation_results",
            [
                {
                    "evaluation_run_id": run["id"],
                    "evaluation_example_id": g.example_id,
                    "predicted_json": g.predicted,
                    "expected_json": g.expected,
                    "severity_correct": g.severity_correct,
                    "component_correct": g.component_correct,
                    "both_correct": g.both_correct,
                }
                for g in grades
            ],
        )
    return run


async def _latest_run_for(db: SupabaseClient, prompt_version_id: str) -> Row | None:
    rows = await db.select(
        "evaluation_runs",
        filters={"prompt_version_id": f"eq.{prompt_version_id}"},
        order="created_at.desc",
        limit=1,
    )
    return rows[0] if rows else None


async def _results_for_run(db: SupabaseClient, run_id: str) -> list[Row]:
    return await db.select(
        "evaluation_results",
        filters={"evaluation_run_id": f"eq.{run_id}"},
    )


def _grades_from_stored_results(rows: list[Row]) -> list[ExampleGrade]:
    """Rebuild grades from a persisted run so it can be reused as an arm."""
    return [
        ExampleGrade(
            example_id=row["evaluation_example_id"],
            predicted=row.get("predicted_json"),
            expected=row.get("expected_json") or {},
            severity_correct=bool(row["severity_correct"]),
            component_correct=bool(row["component_correct"]),
            both_correct=bool(row["both_correct"]),
        )
        for row in rows
    ]


def _evaluation_fingerprint(prompt_text: str, examples: list[Row]) -> str:
    """Identify every input that can change an evaluation arm's predictions."""
    payload = {
        "cache_version": EVALUATION_CACHE_VERSION,
        "effective_prompt": build_system_prompt(prompt_text),
        "model": settings.openrouter_model,
        "base_url": settings.openrouter_base_url,
        "temperature": settings.llm_temperature,
        "seed": settings.llm_seed,
        "response_schema": TRIAGE_JSON_SCHEMA,
        "examples": [
            {
                "id": example["id"],
                "report_text": example["report_text"],
                "expected_severity": example["expected_severity"],
                "expected_component": example["expected_component"],
            }
            for example in sorted(examples, key=lambda row: str(row["id"]))
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_cache_valid(
    run: Row,
    stored: list[Row],
    examples: list[Row],
    expected_fingerprint: str,
) -> bool:
    """Require both a matching fingerprint and complete per-example evidence."""
    return run.get("cache_fingerprint") == expected_fingerprint and {
        r["evaluation_example_id"] for r in stored
    } == {e["id"] for e in examples}


# ---------------------------------------------------------------------------
# Assembling the comparison
# ---------------------------------------------------------------------------
def _summary(run: Row, version_name: str) -> EvalRunSummary:
    return EvalRunSummary(
        prompt_version_id=run["prompt_version_id"],
        version_name=version_name,
        severity_accuracy=run["severity_accuracy"],
        component_accuracy=run["component_accuracy"],
        overall_accuracy=run["overall_accuracy"],
        regression_count=run["regression_count"],
        created_at=run["created_at"],
    )


def _comparison(
    previous_run: Row,
    previous_name: str,
    active_run: Row,
    active_name: str,
    improved_count: int,
    example_count: int,
    previous_is_cached: bool = False,
    candidate_decision: str | None = None,
    regression_details: list[RegressionDetail] | None = None,
    remaining_error_reduction: float = 0.0,
) -> EvalComparison:
    previous = _summary(previous_run, previous_name)
    active = _summary(active_run, active_name)
    return EvalComparison(
        previous=previous,
        active=active,
        overall_delta=active.overall_accuracy - previous.overall_accuracy,
        severity_delta=active.severity_accuracy - previous.severity_accuracy,
        component_delta=active.component_accuracy - previous.component_accuracy,
        regression_count=active.regression_count,
        protected_regression_count=sum(
            detail.protected for detail in (regression_details or [])
        ),
        regression_details=regression_details or [],
        remaining_error_reduction=remaining_error_reduction,
        ordinary_regression_limit=MAX_ORDINARY_REGRESSIONS,
        improved_count=improved_count,
        example_count=example_count,
        # max(): with a reused previous arm the active run is always the newer
        # of the two, so this reports when the comparison was actually made.
        evaluated_at=max(previous.created_at, active.created_at),
        previous_is_cached=previous_is_cached,
        candidate_decision=candidate_decision,
    )


def _regression_pairs(
    control: list[ExampleGrade], candidate: list[ExampleGrade]
) -> list[tuple[ExampleGrade, ExampleGrade]]:
    control_by_id = {grade.example_id: grade for grade in control}
    return [
        (control_by_id[grade.example_id], grade)
        for grade in candidate
        if grade.example_id in control_by_id
        and control_by_id[grade.example_id].both_correct
        and not grade.both_correct
    ]


def _regression_details(
    examples: list[Row],
    control: list[ExampleGrade],
    candidate: list[ExampleGrade],
) -> list[RegressionDetail]:
    """Return auditable evidence for every deterministic exact-match regression."""
    examples_by_id = {example["id"]: example for example in examples}
    pairs = _regression_pairs(control, candidate)

    def is_protected(candidate_grade: ExampleGrade) -> bool:
        if candidate_grade.expected.get("severity") not in PROTECTED_SEVERITIES:
            return False
        prediction = candidate_grade.predicted
        return (
            prediction is None
            or prediction.get("severity") not in TOLERATED_PROTECTED_SEVERITIES
            or prediction.get("component")
            != candidate_grade.expected.get("component")
        )

    return [
        RegressionDetail(
            example_id=candidate_grade.example_id,
            report_text=examples_by_id[candidate_grade.example_id]["report_text"],
            expected=candidate_grade.expected,
            control_prediction=control_grade.predicted,
            candidate_prediction=candidate_grade.predicted,
            protected=is_protected(candidate_grade),
        )
        for control_grade, candidate_grade in pairs
    ]


def _remaining_error_reduction(control: Accuracy, candidate: Accuracy) -> float:
    """Fraction of the control's remaining exact-match errors eliminated."""
    remaining_error = 1.0 - control.overall_accuracy
    if remaining_error <= 0:
        return 0.0
    return (candidate.overall_accuracy - control.overall_accuracy) / remaining_error


def _passes_promotion_gate(
    control: Accuracy,
    candidate: Accuracy,
    regression_details: list[RegressionDetail],
) -> bool:
    """Apply every deterministic guardrail required to activate a candidate."""
    protected_regressions = sum(detail.protected for detail in regression_details)
    ordinary_regressions = len(regression_details) - protected_regressions
    return (
        _remaining_error_reduction(control, candidate) + 1e-12
        >= MIN_REMAINING_ERROR_REDUCTION
        and ordinary_regressions <= MAX_ORDINARY_REGRESSIONS
        and protected_regressions == 0
        and candidate.severity_accuracy >= control.severity_accuracy
        and candidate.component_accuracy >= control.component_accuracy
    )


async def _evaluate_candidate(
    db: SupabaseClient,
    llm_client: AsyncHTTPClient,
    examples: list[Row],
    active: Row,
    candidate: Row,
    *,
    semaphore: asyncio.Semaphore,
    force: bool,
    on_progress: ProgressCallback | None,
) -> EvalComparison:
    """Evaluate a candidate against the live prompt, then resolve it atomically.

    The active arm is reused only when its fingerprint and complete stored
    evidence match. The candidate arm is always scored fresh.
    """
    active_fingerprint = _evaluation_fingerprint(active["prompt_text"], examples)
    candidate_fingerprint = _evaluation_fingerprint(
        candidate["prompt_text"], examples
    )
    active_run: Row | None = None
    active_grades: list[ExampleGrade] | None = None
    active_is_cached = False

    if not force:
        latest_active_run = await _latest_run_for(db, active["id"])
        if latest_active_run is not None:
            stored = await _results_for_run(db, latest_active_run["id"])
            if _is_cache_valid(
                latest_active_run, stored, examples, active_fingerprint
            ):
                active_run = latest_active_run
                active_grades = _grades_from_stored_results(stored)
                active_is_cached = True

    progress = _Progress(
        len(examples) if active_grades is not None else len(examples) * 2,
        on_progress,
    )
    if active_grades is None:
        active_grades, candidate_grades = await asyncio.gather(
            _predict_all(
                llm_client,
                examples,
                active["prompt_text"],
                semaphore=semaphore,
                arm="active",
                progress=progress,
            ),
            _predict_all(
                llm_client,
                examples,
                candidate["prompt_text"],
                semaphore=semaphore,
                arm="candidate",
                progress=progress,
            ),
        )
    else:
        candidate_grades = await _predict_all(
            llm_client,
            examples,
            candidate["prompt_text"],
            semaphore=semaphore,
            arm="candidate",
            progress=progress,
        )

    active_accuracy = aggregate(active_grades)
    candidate_accuracy = aggregate(candidate_grades)
    regressions = count_regressions(active_grades, candidate_grades)
    improvements = count_improvements(active_grades, candidate_grades)
    regression_details = _regression_details(examples, active_grades, candidate_grades)
    error_reduction = _remaining_error_reduction(active_accuracy, candidate_accuracy)
    accepted = _passes_promotion_gate(
        active_accuracy, candidate_accuracy, regression_details
    )

    if active_run is None:
        active_run = await _store_run(
            db,
            active["id"],
            active_grades,
            active_accuracy,
            0,
            active_fingerprint,
        )
    candidate_run = await _store_run(
        db,
        candidate["id"],
        candidate_grades,
        candidate_accuracy,
        regressions,
        candidate_fingerprint,
    )
    await resolve_candidate(
        db,
        candidate["id"],
        active["id"],
        accept=accepted,
    )

    decision = "promoted" if accepted else "rejected"
    return _comparison(
        active_run,
        active["version_name"],
        candidate_run,
        candidate["version_name"],
        improvements,
        len(examples),
        previous_is_cached=active_is_cached,
        candidate_decision=decision,
        regression_details=regression_details,
        remaining_error_reduction=error_reduction,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def run_evaluation(
    db: SupabaseClient,
    llm_client: AsyncHTTPClient,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> EvalComparison:
    """Score the active prompt, comparing against the previous version.

    Fingerprints automatically invalidate stale stored arms. `force=True`
    bypasses an otherwise valid cache for an explicit fresh measurement.
    """
    examples = await db.select("evaluation_examples", order="id.asc")
    if not examples:
        raise EvaluationError(
            "No evaluation examples found. Did you run supabase/seed.sql?"
        )

    active = await get_active_prompt(db)
    candidate = await get_candidate_prompt(db)
    previous = await get_previous_prompt(db, active)
    semaphore = asyncio.Semaphore(max(1, settings.eval_concurrency))

    if candidate is not None:
        return await _evaluate_candidate(
            db,
            llm_client,
            examples,
            active,
            candidate,
            semaphore=semaphore,
            force=force,
            on_progress=on_progress,
        )

    # Fresh install: nothing to compare against. Score once and report it for
    # both sides so the UI shows a real number rather than a fabricated delta.
    if previous is None:
        progress = _Progress(len(examples), on_progress)
        grades = await _predict_all(
            llm_client,
            examples,
            active["prompt_text"],
            semaphore=semaphore,
            arm="active",
            progress=progress,
        )
        run = await _store_run(
            db,
            active["id"],
            grades,
            aggregate(grades),
            0,
            _evaluation_fingerprint(active["prompt_text"], examples),
        )
        return _comparison(
            run, active["version_name"], run, active["version_name"], 0, len(examples)
        )

    # Try to reuse the previous version's stored run.
    cached_grades: list[ExampleGrade] | None = None
    previous_run: Row | None = None
    previous_fingerprint = _evaluation_fingerprint(previous["prompt_text"], examples)
    if not force:
        candidate = await _latest_run_for(db, previous["id"])
        if candidate is not None:
            stored = await _results_for_run(db, candidate["id"])
            if _is_cache_valid(
                candidate, stored, examples, previous_fingerprint
            ):
                cached_grades = _grades_from_stored_results(stored)
                previous_run = candidate

    total = len(examples) if cached_grades is not None else len(examples) * 2
    progress = _Progress(total, on_progress)

    if cached_grades is not None:
        previous_grades = cached_grades
        active_grades = await _predict_all(
            llm_client,
            examples,
            active["prompt_text"],
            semaphore=semaphore,
            arm="active",
            progress=progress,
        )
    else:
        previous_grades, active_grades = await asyncio.gather(
            _predict_all(
                llm_client,
                examples,
                previous["prompt_text"],
                semaphore=semaphore,
                arm="previous",
                progress=progress,
            ),
            _predict_all(
                llm_client,
                examples,
                active["prompt_text"],
                semaphore=semaphore,
                arm="active",
                progress=progress,
            ),
        )

    regressions = count_regressions(previous_grades, active_grades)
    improvements = count_improvements(previous_grades, active_grades)

    if previous_run is None:
        previous_run = await _store_run(
            db,
            previous["id"],
            previous_grades,
            aggregate(previous_grades),
            0,
            previous_fingerprint,
        )
    previous_accuracy = aggregate(previous_grades)
    active_accuracy = aggregate(active_grades)
    regression_details = _regression_details(examples, previous_grades, active_grades)
    active_run = await _store_run(
        db,
        active["id"],
        active_grades,
        active_accuracy,
        regressions,
        _evaluation_fingerprint(active["prompt_text"], examples),
    )

    return _comparison(
        previous_run,
        previous["version_name"],
        active_run,
        active["version_name"],
        improvements,
        len(examples),
        previous_is_cached=cached_grades is not None,
        regression_details=regression_details,
        remaining_error_reduction=_remaining_error_reduction(
            previous_accuracy, active_accuracy
        ),
    )


async def _improved_count_for_run(
    db: SupabaseClient, previous_run_id: str, active_run_id: str
) -> int:
    """Recompute improvements from stored per-example results."""
    if previous_run_id == active_run_id:
        return 0
    previous_rows = await db.select(
        "evaluation_results",
        columns="evaluation_example_id,both_correct",
        filters={"evaluation_run_id": f"eq.{previous_run_id}"},
    )
    active_rows = await db.select(
        "evaluation_results",
        columns="evaluation_example_id,both_correct",
        filters={"evaluation_run_id": f"eq.{active_run_id}"},
    )
    previous_map = {
        r["evaluation_example_id"]: r["both_correct"] for r in previous_rows
    }
    return sum(
        1
        for r in active_rows
        if r["evaluation_example_id"] in previous_map
        and not previous_map[r["evaluation_example_id"]]
        and r["both_correct"]
    )


async def _stored_comparison_evidence(
    db: SupabaseClient,
    control_run_id: str,
    candidate_run_id: str,
) -> tuple[list[RegressionDetail], float]:
    """Reconstruct regression evidence and error reduction after a reload."""
    if control_run_id == candidate_run_id:
        return [], 0.0
    control_rows, candidate_rows, examples = await asyncio.gather(
        _results_for_run(db, control_run_id),
        _results_for_run(db, candidate_run_id),
        db.select("evaluation_examples", order="id.asc"),
    )
    control_grades = _grades_from_stored_results(control_rows)
    candidate_grades = _grades_from_stored_results(candidate_rows)
    return (
        _regression_details(examples, control_grades, candidate_grades),
        _remaining_error_reduction(
            aggregate(control_grades), aggregate(candidate_grades)
        ),
    )


async def get_latest_evaluation(db: SupabaseClient) -> EvalComparison | None:
    """Most recent stored evaluation for the current previous/active pair.

    Runs are paired by prompt version rather than by a batch id, which keeps the
    schema exactly as specified. Returns None when either arm has never run.
    """
    active = await get_active_prompt(db)

    # Candidate decisions remain visible after reload, including rejected
    # candidates that never became active.
    resolved = [
        row
        for row in await list_prompts(db)
        if row.get("evaluation_decision") in {"promoted", "rejected"}
        and row.get("evaluated_against_prompt_id")
    ]
    if resolved:
        candidate = max(
            resolved,
            key=lambda row: str(row.get("evaluated_at") or row.get("created_at") or ""),
        )
        control = next(
            (
                row
                for row in await list_prompts(db)
                if row["id"] == candidate["evaluated_against_prompt_id"]
            ),
            None,
        )
        candidate_run = await _latest_run_for(db, candidate["id"])
        control_run = (
            await _latest_run_for(db, control["id"]) if control is not None else None
        )
        if (
            candidate_run is not None
            and control_run is not None
            and control is not None
        ):
            improved = await _improved_count_for_run(
                db, control_run["id"], candidate_run["id"]
            )
            details, error_reduction = await _stored_comparison_evidence(
                db, control_run["id"], candidate_run["id"]
            )
            return _comparison(
                control_run,
                control["version_name"],
                candidate_run,
                candidate["version_name"],
                improved,
                await _example_count(db),
                candidate_decision=candidate["evaluation_decision"],
                regression_details=details,
                remaining_error_reduction=error_reduction,
            )

    previous = await get_previous_prompt(db, active)

    active_run = await _latest_run_for(db, active["id"])
    if active_run is None:
        return None

    if previous is None:
        return _comparison(
            active_run,
            active["version_name"],
            active_run,
            active["version_name"],
            0,
            await _example_count(db),
        )

    previous_run = await _latest_run_for(db, previous["id"])
    if previous_run is None:
        return None

    improved = await _improved_count_for_run(db, previous_run["id"], active_run["id"])
    details, error_reduction = await _stored_comparison_evidence(
        db, previous_run["id"], active_run["id"]
    )
    return _comparison(
        previous_run,
        previous["version_name"],
        active_run,
        active["version_name"],
        improved,
        await _example_count(db),
        regression_details=details,
        remaining_error_reduction=error_reduction,
    )


async def _example_count(db: SupabaseClient) -> int:
    rows = await db.select("evaluation_examples", columns="id")
    return len(rows)
