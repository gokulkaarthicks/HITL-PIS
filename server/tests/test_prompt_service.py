"""Tests for prompt improvement assembly (pure functions only)."""

import pytest

from app.prompt_service import (
    build_improved_prompt_text,
    get_baseline_prompt,
    get_previous_prompt,
    group_reference_corrections,
    improve_prompt,
    next_version_name,
    summarize_confusions,
)
from tests.fakes import FakeSupabase

BASELINE = "You are a bug report triage assistant."


def correction(
    bug_id: str,
    text: str,
    llm: tuple[str, str] | None,
    human: tuple[str, str],
    reviewed_at: str = "2026-01-01T00:00:00Z",
) -> dict:
    return {
        "id": bug_id,
        "report_text": text,
        "llm_output_json": (
            {"severity": llm[0], "component": llm[1], "rationale": "llm"}
            if llm
            else None
        ),
        "human_corrected_json": {
            "severity": human[0],
            "component": human[1],
            "rationale": "human verified rationale",
        },
        "reviewed_at": reviewed_at,
    }


def test_confirmations_are_not_used_as_reference_cases():
    rows = [
        correction("1", "agreed report", ("low", "frontend"), ("low", "frontend")),
        correction("2", "fixed report", ("low", "backend"), ("critical", "payments")),
    ]
    groups = group_reference_corrections(rows)
    assert [primary["id"] for primary, _nuances in groups] == ["2"]


def test_selection_prefers_diverse_corrected_label_pairs():
    rows = [
        correction("1", "first auth", ("low", "backend"), ("high", "auth")),
        correction("2", "second auth", ("low", "backend"), ("high", "auth")),
        correction("3", "payment", ("low", "backend"), ("critical", "payments")),
    ]
    groups = group_reference_corrections(rows)
    assert [primary["id"] for primary, _nuances in groups] == ["3", "1"]


def test_same_outcome_is_rendered_as_one_example_with_nuances():
    rows = [
        correction("1", "first auth case", ("low", "backend"), ("high", "auth")),
        correction(
            "2", "second auth case", ("medium", "backend"), ("high", "auth")
        ),
    ]

    text = build_improved_prompt_text(BASELINE, rows)

    assert text.count("### Example") == 1
    assert "first auth case" in text
    assert "second auth case" in text
    assert "Related reviewed nuances with the same verified labels" in text


def test_selection_includes_every_distinct_corrected_pair():
    pairs = [
        ("high", "auth"),
        ("critical", "payments"),
        ("medium", "mobile"),
        ("low", "frontend"),
        ("high", "database"),
        ("critical", "infrastructure"),
    ]
    rows = [
        correction(str(i), f"report {i}", ("low", "backend"), pair)
        for i, pair in enumerate(pairs)
    ]
    assert len(group_reference_corrections(rows)) == 6


def test_selection_is_deterministic_regardless_of_input_order():
    rows = [
        correction(
            "1", "a", ("low", "backend"), ("high", "auth"), "2026-01-01T00:00:00Z"
        ),
        correction(
            "2", "b", ("low", "backend"), ("high", "auth"), "2026-01-02T00:00:00Z"
        ),
        correction(
            "3", "c", ("low", "backend"), ("high", "auth"), "2026-01-03T00:00:00Z"
        ),
    ]
    forward = [r["id"] for r, _ in group_reference_corrections(rows)]
    backward = [
        r["id"] for r, _ in group_reference_corrections(list(reversed(rows)))
    ]
    assert forward == backward == ["1"]


def test_stronger_disagreement_wins_for_the_same_corrected_pair():
    rows = [
        correction("1", "one axis", ("medium", "auth"), ("high", "auth")),
        correction("2", "two axes", ("low", "backend"), ("high", "auth")),
    ]
    assert [r["id"] for r, _ in group_reference_corrections(rows)] == ["2"]


def test_rows_without_usable_human_labels_are_dropped():
    bad = correction("1", "x", ("low", "backend"), ("high", "auth"))
    bad["human_corrected_json"] = {"severity": "", "component": "", "rationale": ""}
    assert group_reference_corrections([bad]) == []


def test_placeholder_rationale_is_excluded_from_worked_examples():
    row = correction("1", "x", ("low", "backend"), ("high", "auth"))
    row["human_corrected_json"]["rationale"] = "x"
    assert group_reference_corrections([row]) == []
    text = build_improved_prompt_text(BASELINE, [row])
    assert "Calibration from human review" in text
    assert "Distinctive human-verified reference cases" not in text


def test_confusions_are_tallied_per_axis_and_ranked():
    rows = [
        correction("1", "a", ("high", "backend"), ("critical", "payments")),
        correction("2", "b", ("high", "frontend"), ("critical", "payments")),
        correction("3", "c", ("low", "backend"), ("medium", "database")),
    ]
    severity_lines, component_lines = summarize_confusions(rows)
    assert "Prefer `critical` over `high`" in severity_lines[0]
    assert any("Prefer `medium` over `low`" in s for s in severity_lines)
    assert len(component_lines) == 3


def test_confirmations_produce_no_confusion_lines():
    rows = [correction("1", "a", ("low", "frontend"), ("low", "frontend"))]
    severity_lines, component_lines = summarize_confusions(rows)
    assert severity_lines == []
    assert component_lines == []


def test_improved_prompt_contains_baseline_calibration_and_examples():
    rows = [
        correction(
            "1", "Checkout is down", ("low", "backend"), ("critical", "payments")
        )
    ]
    text = build_improved_prompt_text(BASELINE, rows)

    assert text.startswith("# Bug report triage operating prompt")
    assert "## Role, task, and output contract" in text
    assert BASELINE in text
    assert "## Decision process" in text
    assert "Write the rationale in English only" in text
    assert "Calibration from human review" in text
    assert "Prefer `critical` over `low`" in text
    assert "Distinctive human-verified reference cases" in text
    assert "Checkout is down" in text
    assert '"severity": "critical"' in text
    assert "## Final instruction" in text


def test_improved_prompt_is_byte_identical_for_the_same_corrections():
    rows = [
        correction("1", "a", ("low", "backend"), ("high", "auth")),
        correction("2", "b", ("low", "frontend"), ("low", "frontend")),
    ]
    assert build_improved_prompt_text(BASELINE, rows) == build_improved_prompt_text(
        BASELINE, rows
    )


def test_improved_prompt_omits_calibration_when_model_was_never_wrong():
    rows = [correction("1", "a", ("low", "frontend"), ("low", "frontend"))]
    text = build_improved_prompt_text(BASELINE, rows)
    assert "Calibration from human review" not in text
    assert "Distinctive human-verified reference cases" not in text


def test_version_names_increment():
    assert next_version_name([]) == "v1-improved"
    assert next_version_name([{"id": "a"}, {"id": "b"}]) == "v3-improved"


def prompt_row(pid: str, name: str, created_at: str, active: bool = False) -> dict:
    return {
        "id": pid,
        "version_name": name,
        "prompt_text": f"text for {name}",
        "is_active": active,
        "created_from_corrections_count": 0,
        "created_at": created_at,
    }


@pytest.mark.asyncio
async def test_previous_prompt_is_the_immediately_prior_version():
    db = FakeSupabase(
        {
            "prompt_versions": [
                prompt_row("p1", "v1-baseline", "2026-01-01T00:00:00+00:00"),
                prompt_row("p2", "v2-improved", "2026-02-01T00:00:00+00:00"),
                prompt_row("p3", "v3-improved", "2026-03-01T00:00:00+00:00", True),
            ]
        }
    )
    active = db.tables["prompt_versions"][2]
    previous = await get_previous_prompt(db, active)
    assert previous is not None
    assert previous["version_name"] == "v2-improved"


@pytest.mark.asyncio
async def test_previous_prompt_is_none_for_the_oldest_version():
    """A fresh install has nothing to compare against."""
    db = FakeSupabase(
        {
            "prompt_versions": [
                prompt_row("p1", "v1-baseline", "2026-01-01T00:00:00+00:00", True),
            ]
        }
    )
    active = db.tables["prompt_versions"][0]
    assert await get_previous_prompt(db, active) is None


@pytest.mark.asyncio
async def test_previous_prompt_ignores_versions_newer_than_active():
    """Reactivating an older version must not pick a newer one as 'previous'."""
    db = FakeSupabase(
        {
            "prompt_versions": [
                prompt_row("p1", "v1-baseline", "2026-01-01T00:00:00+00:00"),
                prompt_row("p2", "v2-improved", "2026-02-01T00:00:00+00:00", True),
                prompt_row("p3", "v3-improved", "2026-03-01T00:00:00+00:00"),
            ]
        }
    )
    active = db.tables["prompt_versions"][1]
    previous = await get_previous_prompt(db, active)
    assert previous is not None
    assert previous["version_name"] == "v1-baseline"


@pytest.mark.asyncio
async def test_baseline_is_pinned_by_name_not_by_timestamp():
    """The composition root must not move when a version has an odd timestamp."""
    db = FakeSupabase(
        {
            "prompt_versions": [
                prompt_row("p1", "v1-baseline", "2026-07-01T00:00:00+00:00"),
                prompt_row("p2", "v2-improved", "2026-01-01T00:00:00+00:00", True),
            ]
        }
    )
    baseline = await get_baseline_prompt(db)
    assert baseline["version_name"] == "v1-baseline"


@pytest.mark.asyncio
async def test_baseline_falls_back_to_oldest_when_seed_name_is_absent():
    db = FakeSupabase(
        {
            "prompt_versions": [
                prompt_row("p2", "v2-improved", "2026-02-01T00:00:00+00:00", True),
                prompt_row("p1", "renamed-control", "2026-01-01T00:00:00+00:00"),
            ]
        }
    )
    baseline = await get_baseline_prompt(db)
    assert baseline["version_name"] == "renamed-control"


@pytest.mark.asyncio
async def test_improve_creates_inactive_candidate_without_replacing_active_prompt():
    reviewed = correction(
        "b1", "checkout is down", ("high", "backend"), ("critical", "payments")
    )
    reviewed["status"] = "reviewed"
    db = FakeSupabase(
        {
            "prompt_versions": [
                {
                    **prompt_row(
                        "p1", "v1-baseline", "2026-01-01T00:00:00+00:00", True
                    ),
                    "lifecycle_status": "active",
                }
            ],
            "bug_reports": [reviewed],
        }
    )

    candidate = await improve_prompt(db)

    assert candidate["lifecycle_status"] == "candidate"
    assert candidate["is_active"] is False
    assert db.tables["prompt_versions"][0]["is_active"] is True
