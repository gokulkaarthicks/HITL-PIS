"""Request/response models and the shared label vocabulary.

The vocabulary lives here and is imported by the LLM client (to build the
JSON schema), the grader (to normalize labels) and the API layer (to validate
human corrections), so the four places can never drift apart.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "high", "medium", "low"]
Component = Literal[
    "frontend",
    "backend",
    "mobile",
    "auth",
    "payments",
    "database",
    "infrastructure",
    "unknown",
]

SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
COMPONENTS: tuple[str, ...] = (
    "frontend",
    "backend",
    "mobile",
    "auth",
    "payments",
    "database",
    "infrastructure",
    "unknown",
)


class Triage(BaseModel):
    """The structured triage output, produced by the LLM or corrected by a human."""

    severity: Severity
    component: Component
    rationale: str = Field(default="", max_length=2000)

    @field_validator("severity", "component", mode="before")
    @classmethod
    def _normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class CreateBugRequest(BaseModel):
    report_text: str = Field(min_length=10, max_length=5000)

    @field_validator("report_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 10:
            raise ValueError("report_text must be at least 10 characters")
        return stripped


class RunRequest(BaseModel):
    """Optional body for POST /bugs/{id}/run."""

    reviewer_id: str | None = Field(default=None, max_length=64)


class CorrectionRequest(BaseModel):
    corrected: Triage
    reviewer_id: str = Field(min_length=1, max_length=64)


class EvalRunSummary(BaseModel):
    prompt_version_id: str
    version_name: str
    severity_accuracy: float
    component_accuracy: float
    overall_accuracy: float
    regression_count: int
    created_at: str


class EvalComparison(BaseModel):
    """Before/after metrics returned by POST /eval/run and GET /eval/latest.

    `previous` is the prompt version immediately preceding the active one, not a
    fixed baseline. `previous_is_cached` says whether its score was reused from
    an earlier stored run rather than freshly computed -- the UI must surface
    that so a reused number is never mistaken for a fresh one.
    """

    previous: EvalRunSummary
    active: EvalRunSummary
    overall_delta: float
    severity_delta: float
    component_delta: float
    regression_count: int
    improved_count: int
    example_count: int
    evaluated_at: str
    previous_is_cached: bool = False
