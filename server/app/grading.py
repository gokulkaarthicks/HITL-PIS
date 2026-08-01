"""Deterministic scoring.

No model is involved in judging correctness. A prediction is correct only when
its normalized label string equals the expected label string. `rationale` is
deliberately NOT scored -- it is free text shown to the reviewer for manual
inspection, and any automated scoring of it would need a second model, which
this system intentionally avoids.

Every function here is pure, which is what makes the metrics auditable and the
unit tests meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import Triage


def normalize_label(value: object) -> str:
    """Casefold and trim a label so cosmetic differences never affect scoring."""
    return value.strip().lower() if isinstance(value, str) else ""


@dataclass(frozen=True)
class ExampleGrade:
    example_id: str
    predicted: dict[str, str] | None
    expected: dict[str, str]
    severity_correct: bool
    component_correct: bool
    both_correct: bool


@dataclass(frozen=True)
class Accuracy:
    severity_accuracy: float
    component_accuracy: float
    overall_accuracy: float


def grade_example(
    example_id: str,
    predicted: Triage | None,
    expected_severity: str,
    expected_component: str,
) -> ExampleGrade:
    """Grade one prediction.

    `predicted is None` means the LLM call failed or returned unusable output.
    That counts as wrong on both axes -- a prompt that makes the model produce
    garbage should be penalised, not silently skipped.
    """
    expected = {
        "severity": normalize_label(expected_severity),
        "component": normalize_label(expected_component),
    }

    if predicted is None:
        return ExampleGrade(
            example_id=example_id,
            predicted=None,
            expected=expected,
            severity_correct=False,
            component_correct=False,
            both_correct=False,
        )

    severity_correct = normalize_label(predicted.severity) == expected["severity"]
    component_correct = normalize_label(predicted.component) == expected["component"]

    return ExampleGrade(
        example_id=example_id,
        predicted={
            "severity": normalize_label(predicted.severity),
            "component": normalize_label(predicted.component),
            "rationale": predicted.rationale,
        },
        expected=expected,
        severity_correct=severity_correct,
        component_correct=component_correct,
        both_correct=severity_correct and component_correct,
    )


def aggregate(grades: list[ExampleGrade]) -> Accuracy:
    """Mean accuracy across grades. Empty input scores zero, not NaN."""
    total = len(grades)
    if total == 0:
        return Accuracy(0.0, 0.0, 0.0)
    return Accuracy(
        severity_accuracy=sum(g.severity_correct for g in grades) / total,
        component_accuracy=sum(g.component_correct for g in grades) / total,
        overall_accuracy=sum(g.both_correct for g in grades) / total,
    )


def _by_example(grades: list[ExampleGrade]) -> dict[str, ExampleGrade]:
    return {g.example_id: g for g in grades}


def count_regressions(
    baseline: list[ExampleGrade], candidate: list[ExampleGrade]
) -> int:
    """Examples the baseline got fully right that the candidate gets wrong.

    This is the guardrail metric: a candidate prompt can raise overall accuracy
    while breaking cases that previously worked, and that trade needs to be
    visible rather than averaged away.
    """
    base = _by_example(baseline)
    return sum(
        1
        for g in candidate
        if g.example_id in base and base[g.example_id].both_correct and not g.both_correct
    )


def count_improvements(
    baseline: list[ExampleGrade], candidate: list[ExampleGrade]
) -> int:
    """Examples the baseline got wrong that the candidate gets fully right."""
    base = _by_example(baseline)
    return sum(
        1
        for g in candidate
        if g.example_id in base and not base[g.example_id].both_correct and g.both_correct
    )
