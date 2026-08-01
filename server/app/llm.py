"""OpenRouter client for bug triage.

The model is asked for a JSON-schema-constrained response so the label
vocabulary is enforced by the provider rather than by fragile parsing. We still
validate what comes back: a provider that ignores the schema must not be able
to poison the evaluation with an out-of-vocabulary label.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .config import settings
from .http_client import AsyncHTTPClient, OutboundHTTPClient, OutboundHTTPError
from .schemas import COMPONENTS, SEVERITIES, Triage

TRIAGE_JSON_SCHEMA: dict[str, Any] = {
    "name": "bug_triage",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": list(SEVERITIES)},
            "component": {"type": "string", "enum": list(COMPONENTS)},
            "rationale": {"type": "string"},
        },
        "required": ["severity", "component", "rationale"],
        "additionalProperties": False,
    },
}


class LLMError(RuntimeError):
    """Raised when the provider fails or returns something unusable."""


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1] if "```" in candidate[3:] else candidate
        candidate = candidate.removeprefix("json").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("Model response did not contain a JSON object")
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Model response was not a JSON object")
    return parsed


async def classify(
    client: AsyncHTTPClient, report_text: str, prompt_text: str
) -> Triage:
    """Run one triage call. Raises LLMError on any failure."""
    if not settings.openrouter_api_key:
        raise LLMError(
            "OPENROUTER_API_KEY is not set (see server/.env.example)."
        )

    body: dict[str, Any] = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": f"Bug report:\n{report_text}"},
        ],
        "temperature": settings.llm_temperature,
        "seed": settings.llm_seed,
        "response_format": {"type": "json_schema", "json_schema": TRIAGE_JSON_SCHEMA},
    }

    try:
        response = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=settings.llm_timeout_seconds,
        )
    except (httpx.HTTPError, OutboundHTTPError) as exc:
        raise LLMError(f"Could not reach OpenRouter: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(
            f"OpenRouter returned {response.status_code}: {response.text[:400]}"
        )

    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected OpenRouter response shape: {exc}") from exc

    if not content:
        raise LLMError("OpenRouter returned an empty completion")

    parsed = _extract_json_object(content)
    try:
        return Triage.model_validate(parsed)
    except Exception as exc:  # pydantic validation error
        raise LLMError(f"Model output failed validation: {exc}") from exc


def build_llm_client() -> OutboundHTTPClient:
    return OutboundHTTPClient(timeout=settings.llm_timeout_seconds)
