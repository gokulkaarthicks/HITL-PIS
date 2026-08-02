"""End-to-end test of the evaluation loop with a scripted LLM.

Proves the orchestration: the active prompt is compared against the previous
version, the previous arm is reused from stored results when it is still valid,
and a prompt that fixes two cases while breaking one reports both the gain and
the regression.
"""

from __future__ import annotations

import pytest

from app import evaluation as evaluation_module
from app.config import settings
from app.evaluation import (
    EvaluationError,
    _passes_promotion_gate,
    _regression_details,
    get_latest_evaluation,
    run_evaluation,
)
from app.grading import Accuracy, grade_example
from app.schemas import RegressionDetail, Triage
from tests.fakes import FakeSupabase

IMPROVED_MARKER = "Calibration from human review"

EXAMPLES = [
    {
        "id": "ex1",
        "report_text": "checkout down",
        "expected_severity": "critical",
        "expected_component": "payments",
    },
    {
        "id": "ex2",
        "report_text": "reset broken",
        "expected_severity": "high",
        "expected_component": "auth",
    },
    {
        "id": "ex3",
        "report_text": "button shifted",
        "expected_severity": "low",
        "expected_component": "frontend",
    },
    {
        "id": "ex4",
        "report_text": "etl drops rows",
        "expected_severity": "high",
        "expected_component": "database",
    },
]

# The older prompt gets ex3 right only. The improved prompt fixes ex1 and ex2
# but breaks ex3 -- a real accuracy gain that still carries one regression.
BASELINE_PREDICTIONS = {
    "checkout down": ("high", "backend"),
    "reset broken": ("medium", "backend"),
    "button shifted": ("low", "frontend"),
    "etl drops rows": ("medium", "backend"),
}
IMPROVED_PREDICTIONS = {
    "checkout down": ("critical", "payments"),
    "reset broken": ("high", "auth"),
    "button shifted": ("medium", "frontend"),
    "etl drops rows": ("medium", "backend"),
}


def make_db(with_improved_prompt: bool) -> FakeSupabase:
    prompts = [
        {
            "id": "p1",
            "version_name": "v1-baseline",
            "prompt_text": "baseline prompt",
            "is_active": not with_improved_prompt,
            "created_from_corrections_count": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    if with_improved_prompt:
        prompts.append(
            {
                "id": "p2",
                "version_name": "v2-improved",
                "prompt_text": f"baseline prompt\n\n## {IMPROVED_MARKER}\n...",
                "is_active": True,
                "created_from_corrections_count": 3,
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        )
    return FakeSupabase(
        {
            "prompt_versions": prompts,
            "evaluation_examples": [dict(e) for e in EXAMPLES],
            "evaluation_runs": [],
            "evaluation_results": [],
        }
    )


def make_candidate_db() -> FakeSupabase:
    return FakeSupabase(
        {
            "prompt_versions": [
                {
                    "id": "p1",
                    "version_name": "v1-baseline",
                    "prompt_text": "baseline prompt",
                    "is_active": True,
                    "lifecycle_status": "active",
                    "created_from_corrections_count": 0,
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "p2",
                    "version_name": "v2-improved",
                    "prompt_text": f"baseline prompt\n\n## {IMPROVED_MARKER}\n...",
                    "is_active": False,
                    "lifecycle_status": "candidate",
                    "created_from_corrections_count": 3,
                    "created_at": "2026-02-01T00:00:00+00:00",
                },
            ],
            "evaluation_examples": [dict(e) for e in EXAMPLES],
            "evaluation_runs": [],
            "evaluation_results": [],
        }
    )


def add_candidate(db: FakeSupabase, prompt_id: str = "p2") -> None:
    db.tables["prompt_versions"].append(
        {
            "id": prompt_id,
            "version_name": f"v{prompt_id.removeprefix('p')}-improved",
            "prompt_text": f"baseline prompt\n\n## {IMPROVED_MARKER}\n...",
            "is_active": False,
            "lifecycle_status": "candidate",
            "created_from_corrections_count": 3,
            "created_at": f"2026-0{prompt_id.removeprefix('p')}-01T00:00:00+00:00",
        }
    )


@pytest.fixture
def scripted_llm(monkeypatch):
    """Replace the OpenRouter call with a deterministic lookup."""
    calls: list[str] = []

    async def fake_classify(_client, report_text: str, prompt_text: str) -> Triage:
        calls.append(report_text)
        table = (
            IMPROVED_PREDICTIONS
            if IMPROVED_MARKER in prompt_text
            else BASELINE_PREDICTIONS
        )
        severity, component = table[report_text]
        return Triage(severity=severity, component=component, rationale="scripted")

    monkeypatch.setattr(evaluation_module, "classify", fake_classify)
    return calls


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_with_no_previous_version_scores_one_arm(scripted_llm):
    db = make_db(with_improved_prompt=False)
    result = await run_evaluation(db, llm_client=None)

    assert result.previous.version_name == "v1-baseline"
    assert result.active.version_name == "v1-baseline"
    assert result.previous.overall_accuracy == result.active.overall_accuracy
    assert result.overall_delta == 0.0
    assert result.regression_count == 0
    assert result.example_count == 4
    assert result.previous_is_cached is False
    # One arm only: four examples, four calls.
    assert len(scripted_llm) == 4
    assert len(db.tables["evaluation_runs"]) == 1


@pytest.mark.asyncio
async def test_improved_prompt_reports_gain_and_regression(scripted_llm):
    db = make_db(with_improved_prompt=True)
    result = await run_evaluation(db, llm_client=None)

    # Previous: only ex3 fully correct -> 0.25
    assert result.previous.overall_accuracy == pytest.approx(0.25)
    # Improved: ex1 and ex2 fully correct, ex3 broken -> 0.50
    assert result.active.overall_accuracy == pytest.approx(0.50)
    assert result.overall_delta == pytest.approx(0.25)

    assert result.improved_count == 2  # ex1, ex2
    assert result.regression_count == 1  # ex3

    # Nothing cached yet, so both arms ran.
    assert result.previous_is_cached is False
    assert len(scripted_llm) == 8
    assert len(db.tables["evaluation_runs"]) == 2
    assert len(db.tables["evaluation_results"]) == 8


@pytest.mark.asyncio
async def test_candidate_with_one_ordinary_regression_is_promoted(
    scripted_llm,
):
    db = make_candidate_db()
    result = await run_evaluation(db, llm_client=None)

    assert result.candidate_decision == "promoted"
    assert result.overall_delta == pytest.approx(0.25)
    assert result.remaining_error_reduction == pytest.approx(1 / 3)
    assert result.regression_count == 1
    assert result.protected_regression_count == 0
    assert result.regression_details[0].report_text == "button shifted"
    assert result.regression_details[0].expected == {
        "severity": "low",
        "component": "frontend",
    }
    assert result.regression_details[0].candidate_prediction["severity"] == "medium"
    assert db.tables["prompt_versions"][0]["lifecycle_status"] == "superseded"
    assert db.tables["prompt_versions"][1]["is_active"] is True

    latest = await get_latest_evaluation(db)
    assert latest is not None
    assert latest.candidate_decision == "promoted"
    assert latest.active.version_name == "v2-improved"
    assert latest.regression_details == result.regression_details


@pytest.mark.asyncio
async def test_candidate_with_gain_and_zero_regressions_is_promoted(monkeypatch):
    safe_predictions = {
        **IMPROVED_PREDICTIONS,
        "button shifted": ("low", "frontend"),
    }

    async def safe_classify(_client, report_text: str, prompt_text: str) -> Triage:
        table = (
            safe_predictions if IMPROVED_MARKER in prompt_text else BASELINE_PREDICTIONS
        )
        severity, component = table[report_text]
        return Triage(severity=severity, component=component, rationale="scripted")

    monkeypatch.setattr(evaluation_module, "classify", safe_classify)
    db = make_candidate_db()
    result = await run_evaluation(db, llm_client=None)

    assert result.candidate_decision == "promoted"
    assert result.overall_delta > 0
    assert result.regression_count == 0
    assert db.tables["prompt_versions"][0]["lifecycle_status"] == "superseded"
    assert db.tables["prompt_versions"][1]["is_active"] is True


@pytest.mark.asyncio
async def test_candidate_reuses_fingerprinted_active_run(scripted_llm):
    db = make_db(with_improved_prompt=False)
    await run_evaluation(db, llm_client=None)
    calls_after_active_measurement = len(scripted_llm)
    add_candidate(db)
    events: list[dict] = []

    async def on_progress(event):
        events.append(event)

    result = await run_evaluation(db, llm_client=None, on_progress=on_progress)

    assert len(scripted_llm) - calls_after_active_measurement == 4
    assert len(events) == 4
    assert all(event["total"] == 4 for event in events)
    assert all(event["arm"] == "candidate" for event in events)
    assert result.previous_is_cached is True
    assert result.previous.version_name == "v1-baseline"
    assert result.active.version_name == "v2-improved"


@pytest.mark.asyncio
async def test_candidate_cache_invalidates_when_model_changes(
    scripted_llm, monkeypatch
):
    db = make_db(with_improved_prompt=False)
    await run_evaluation(db, llm_client=None)
    calls_after_active_measurement = len(scripted_llm)
    add_candidate(db)
    monkeypatch.setattr(settings, "openrouter_model", "changed/model")

    result = await run_evaluation(db, llm_client=None)

    assert len(scripted_llm) - calls_after_active_measurement == 8
    assert result.previous_is_cached is False


@pytest.mark.asyncio
async def test_promoted_candidate_results_become_next_active_cache(scripted_llm):
    db = make_db(with_improved_prompt=False)
    await run_evaluation(db, llm_client=None)
    add_candidate(db)
    first_candidate = await run_evaluation(db, llm_client=None)
    assert first_candidate.candidate_decision == "promoted"
    calls_after_promotion = len(scripted_llm)
    add_candidate(db, "p3")

    second_candidate = await run_evaluation(db, llm_client=None)

    assert len(scripted_llm) - calls_after_promotion == 4
    assert second_candidate.previous_is_cached is True


def regression_detail(*, protected: bool = False) -> RegressionDetail:
    return RegressionDetail(
        example_id="example",
        report_text="example report",
        expected={
            "severity": "critical" if protected else "low",
            "component": "frontend",
        },
        control_prediction={
            "severity": "critical" if protected else "low",
            "component": "frontend",
        },
        candidate_prediction={"severity": "high", "component": "frontend"},
        protected=protected,
    )


@pytest.mark.parametrize(
    ("control", "candidate", "regressions"),
    [
        # Less than 30% of the control's remaining error was eliminated.
        (Accuracy(0.60, 0.60, 0.50), Accuracy(0.61, 0.61, 0.64), []),
        # More than two ordinary regressions exceeds the explicit limit.
        (
            Accuracy(0.60, 0.60, 0.50),
            Accuracy(0.70, 0.70, 0.70),
            [regression_detail(), regression_detail(), regression_detail()],
        ),
        # A critical expected label is protected regardless of overall gain.
        (
            Accuracy(0.60, 0.60, 0.50),
            Accuracy(0.70, 0.70, 0.70),
            [regression_detail(protected=True)],
        ),
        # Per-axis accuracy may not decline even when overall accuracy improves.
        (Accuracy(0.80, 0.60, 0.50), Accuracy(0.79, 0.80, 0.70), []),
        (Accuracy(0.60, 0.80, 0.50), Accuracy(0.80, 0.79, 0.70), []),
    ],
)
def test_deterministic_promotion_gate_rejects_failed_guardrails(
    control: Accuracy,
    candidate: Accuracy,
    regressions: list[RegressionDetail],
):
    assert _passes_promotion_gate(control, candidate, regressions) is False


def test_deterministic_promotion_gate_accepts_all_guardrails():
    control = Accuracy(0.60, 0.60, 0.50)
    candidate = Accuracy(0.70, 0.70, 0.70)

    assert (
        _passes_promotion_gate(
            control, candidate, [regression_detail(), regression_detail()]
        )
        is True
    )


def test_critical_to_high_with_correct_component_is_not_protected():
    examples = [{"id": "critical", "report_text": "complete payment outage"}]
    control = [
        grade_example(
            "critical",
            Triage(severity="critical", component="payments"),
            "critical",
            "payments",
        )
    ]
    candidate = [
        grade_example(
            "critical",
            Triage(severity="high", component="payments"),
            "critical",
            "payments",
        )
    ]

    details = _regression_details(examples, control, candidate)

    assert len(details) == 1
    assert details[0].protected is False


@pytest.mark.asyncio
async def test_previous_arm_is_the_immediately_prior_version(scripted_llm):
    """With three versions, v3 is compared against v2 -- not against v1."""
    db = make_db(with_improved_prompt=True)
    db.tables["prompt_versions"][1]["is_active"] = False
    db.tables["prompt_versions"].append(
        {
            "id": "p3",
            "version_name": "v3-improved",
            "prompt_text": f"baseline prompt\n\n## {IMPROVED_MARKER}\nmore",
            "is_active": True,
            "created_from_corrections_count": 6,
            "created_at": "2026-03-01T00:00:00+00:00",
        }
    )
    result = await run_evaluation(db, llm_client=None)

    assert result.previous.version_name == "v2-improved"
    assert result.active.version_name == "v3-improved"


@pytest.mark.asyncio
async def test_regression_count_is_persisted_on_the_active_run(scripted_llm):
    db = make_db(with_improved_prompt=True)
    await run_evaluation(db, llm_client=None)

    runs = {r["prompt_version_id"]: r for r in db.tables["evaluation_runs"]}
    assert runs["p1"]["regression_count"] == 0
    assert runs["p2"]["regression_count"] == 1


# ---------------------------------------------------------------------------
# Caching the previous arm
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_second_run_reuses_the_previous_arm(scripted_llm):
    db = make_db(with_improved_prompt=True)
    await run_evaluation(db, llm_client=None)
    calls_after_first = len(scripted_llm)

    second = await run_evaluation(db, llm_client=None)

    # Only the active arm re-ran: four more calls, not eight.
    assert len(scripted_llm) - calls_after_first == 4
    assert second.previous_is_cached is True
    # Metrics are identical to the uncached run.
    assert second.previous.overall_accuracy == pytest.approx(0.25)
    assert second.active.overall_accuracy == pytest.approx(0.50)
    assert second.regression_count == 1
    assert second.improved_count == 2
    # The cached arm reused its existing row rather than inserting a duplicate.
    previous_runs = [
        r for r in db.tables["evaluation_runs"] if r["prompt_version_id"] == "p1"
    ]
    assert len(previous_runs) == 1


@pytest.mark.asyncio
async def test_force_rescores_the_previous_arm(scripted_llm):
    db = make_db(with_improved_prompt=True)
    await run_evaluation(db, llm_client=None)
    calls_after_first = len(scripted_llm)

    forced = await run_evaluation(db, llm_client=None, force=True)

    assert len(scripted_llm) - calls_after_first == 8
    assert forced.previous_is_cached is False


@pytest.mark.asyncio
async def test_changed_example_set_invalidates_the_cache(scripted_llm):
    db = make_db(with_improved_prompt=True)
    await run_evaluation(db, llm_client=None)
    calls_after_first = len(scripted_llm)

    # A new example means the stored score covers a different denominator.
    db.tables["evaluation_examples"].append(
        {
            "id": "ex5",
            "report_text": "checkout down",
            "expected_severity": "critical",
            "expected_component": "payments",
        }
    )
    result = await run_evaluation(db, llm_client=None)

    assert result.previous_is_cached is False
    assert len(scripted_llm) - calls_after_first == 10  # 5 examples x 2 arms
    assert result.example_count == 5


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_progress_callback_counts_every_example(scripted_llm):
    db = make_db(with_improved_prompt=True)
    events: list[dict] = []

    async def on_progress(event):
        events.append(event)

    await run_evaluation(db, llm_client=None, on_progress=on_progress)

    # Both arms ran: 4 examples x 2.
    assert len(events) == 8
    assert all(e["total"] == 8 for e in events)
    assert [e["completed"] for e in events] == list(range(1, 9))
    assert {e["arm"] for e in events} == {"previous", "active"}


@pytest.mark.asyncio
async def test_progress_total_reflects_a_cached_previous_arm(scripted_llm):
    db = make_db(with_improved_prompt=True)
    await run_evaluation(db, llm_client=None)

    events: list[dict] = []

    async def on_progress(event):
        events.append(event)

    await run_evaluation(db, llm_client=None, on_progress=on_progress)

    # Cached: the total must be the 4 that actually run, not a notional 8.
    assert len(events) == 4
    assert all(e["total"] == 4 for e in events)
    assert all(e["arm"] == "active" for e in events)


# ---------------------------------------------------------------------------
# Read-back and failure handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_latest_reads_back_deltas_from_stored_results(scripted_llm):
    db = make_db(with_improved_prompt=True)
    fresh = await run_evaluation(db, llm_client=None)
    latest = await get_latest_evaluation(db)

    assert latest is not None
    assert latest.previous.version_name == fresh.previous.version_name
    assert latest.overall_delta == pytest.approx(fresh.overall_delta)
    assert latest.improved_count == fresh.improved_count
    assert latest.regression_count == fresh.regression_count


@pytest.mark.asyncio
async def test_latest_is_none_before_any_run():
    db = make_db(with_improved_prompt=True)
    assert await get_latest_evaluation(db) is None


@pytest.mark.asyncio
async def test_failed_llm_calls_score_zero_instead_of_aborting(monkeypatch):
    from app.llm import LLMError

    async def always_fails(_client, _report_text, _prompt_text):
        raise LLMError("provider down")

    monkeypatch.setattr(evaluation_module, "classify", always_fails)
    db = make_db(with_improved_prompt=False)

    result = await run_evaluation(db, llm_client=None)
    assert result.active.overall_accuracy == 0.0
    assert len(db.tables["evaluation_results"]) == 4


@pytest.mark.asyncio
async def test_transient_llm_failure_is_retried(monkeypatch):
    from app.llm import LLMError

    attempts: dict[str, int] = {}

    async def fails_once(_client, report_text, _prompt_text):
        attempts[report_text] = attempts.get(report_text, 0) + 1
        if attempts[report_text] == 1:
            raise LLMError("temporary provider failure")
        return Triage(severity="low", component="frontend")

    monkeypatch.setattr(evaluation_module, "classify", fails_once)
    db = make_db(with_improved_prompt=False)

    await run_evaluation(db, llm_client=None)

    assert set(attempts.values()) == {2}


@pytest.mark.asyncio
async def test_empty_example_set_is_rejected(scripted_llm):
    db = make_db(with_improved_prompt=False)
    db.tables["evaluation_examples"] = []
    with pytest.raises(EvaluationError, match="No evaluation examples"):
        await run_evaluation(db, llm_client=None)
