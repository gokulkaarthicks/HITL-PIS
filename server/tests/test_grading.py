"""Tests for deterministic scoring."""

from app.grading import (
    aggregate,
    count_improvements,
    count_regressions,
    grade_example,
    normalize_label,
)
from app.schemas import Triage


def triage(severity: str, component: str, rationale: str = "r") -> Triage:
    return Triage(severity=severity, component=component, rationale=rationale)


def test_normalize_label_is_case_and_whitespace_insensitive():
    assert normalize_label("  CRITICAL ") == "critical"
    assert normalize_label(None) == ""
    assert normalize_label(42) == ""


def test_exact_match_scores_both_axes():
    grade = grade_example("e1", triage("high", "auth"), "high", "auth")
    assert (grade.severity_correct, grade.component_correct, grade.both_correct) == (
        True,
        True,
        True,
    )


def test_partial_match_is_not_both_correct():
    grade = grade_example("e1", triage("high", "backend"), "high", "auth")
    assert grade.severity_correct is True
    assert grade.component_correct is False
    assert grade.both_correct is False


def test_case_differences_do_not_count_as_errors():
    grade = grade_example("e1", triage("HIGH", "AUTH"), "high", "auth")
    assert grade.both_correct is True


def test_failed_llm_call_counts_as_incorrect_not_skipped():
    grade = grade_example("e1", None, "high", "auth")
    assert grade.predicted is None
    assert grade.both_correct is False
    assert grade.severity_correct is False


def test_rationale_never_affects_scoring():
    match = grade_example("e1", triage("low", "frontend", "totally wrong reason"),
                          "low", "frontend")
    assert match.both_correct is True


def test_aggregate_computes_per_axis_means():
    grades = [
        grade_example("a", triage("high", "auth"), "high", "auth"),
        grade_example("b", triage("high", "backend"), "high", "auth"),
        grade_example("c", triage("low", "auth"), "high", "auth"),
        grade_example("d", None, "high", "auth"),
    ]
    accuracy = aggregate(grades)
    assert accuracy.severity_accuracy == 0.5   # a, b
    assert accuracy.component_accuracy == 0.5  # a, c
    assert accuracy.overall_accuracy == 0.25   # a only


def test_aggregate_of_empty_is_zero_not_nan():
    accuracy = aggregate([])
    assert accuracy.overall_accuracy == 0.0
    assert accuracy.severity_accuracy == 0.0


def test_regressions_count_only_correct_to_incorrect():
    baseline = [
        grade_example("a", triage("high", "auth"), "high", "auth"),      # correct
        grade_example("b", triage("low", "mobile"), "high", "auth"),     # wrong
    ]
    candidate = [
        grade_example("a", triage("low", "auth"), "high", "auth"),       # broke
        grade_example("b", triage("high", "auth"), "high", "auth"),      # fixed
    ]
    assert count_regressions(baseline, candidate) == 1
    assert count_improvements(baseline, candidate) == 1


def test_no_regression_when_candidate_matches_baseline():
    baseline = [grade_example("a", triage("high", "auth"), "high", "auth")]
    candidate = [grade_example("a", triage("high", "auth"), "high", "auth")]
    assert count_regressions(baseline, candidate) == 0
    assert count_improvements(baseline, candidate) == 0


def test_unmatched_example_ids_are_ignored():
    baseline = [grade_example("a", triage("high", "auth"), "high", "auth")]
    candidate = [grade_example("z", None, "high", "auth")]
    assert count_regressions(baseline, candidate) == 0
