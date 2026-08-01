"""Environment-driven configuration.

Every secret is read from the environment. Nothing is defaulted to a real
credential, and `validate()` fails loudly at startup rather than letting the
app boot into a state where the first request 500s.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Optional: absent on Cloudflare Workers, where env vars are injected.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _worker_binding(env: Any, name: str) -> str | None:
    """Read a Cloudflare binding without depending on Pyodide locally."""
    try:
        raw = getattr(env, name)
    except (AttributeError, TypeError):
        return None
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


@dataclass
class Settings:
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL").rstrip("/"))
    supabase_service_key: str = field(
        default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY")
    )

    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    openrouter_base_url: str = field(
        default_factory=lambda: _env(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
    )
    openrouter_model: str = field(
        default_factory=lambda: _env(
            "OPENROUTER_MODEL", "deepseek/deepseek-v4-flash"
        )
    )

    # Deterministic decoding so that a rerun of the same evaluation on the same
    # prompt yields the same labels. Accuracy deltas must come from the prompt,
    # not from sampling noise.
    llm_temperature: float = field(
        default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0)
    )
    llm_seed: int = field(default_factory=lambda: _env_int("LLM_SEED", 7))
    # 25s rather than 60s: this model answers in a few seconds, and the timeout
    # is what sets the worst-case evaluation duration, not the typical one.
    llm_timeout_seconds: float = field(
        default_factory=lambda: _env_float("LLM_TIMEOUT_SECONDS", 25.0)
    )
    # Total in-flight LLM calls during an evaluation, shared across both arms.
    # Raise cautiously: a rate-limited call scores as *incorrect*, so pushing
    # this too high corrupts accuracy rather than merely slowing the run.
    eval_concurrency: int = field(
        default_factory=lambda: _env_int("EVAL_CONCURRENCY", 8)
    )

    # Few-shot examples embedded into an improved prompt.
    max_few_shot_examples: int = field(
        default_factory=lambda: _env_int("MAX_FEW_SHOT_EXAMPLES", 6)
    )

    cors_allow_origins: str = field(
        default_factory=lambda: _env("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    def missing(self) -> list[str]:
        """Names of required settings that are absent."""
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_key,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
        }
        return [name for name, value in required.items() if not value]

    def bind_worker_env(self, env: Any) -> None:
        """Apply Cloudflare Worker vars and secrets to this settings object.

        Worker bindings are JavaScript object attributes rather than entries in
        ``os.environ``. The Worker adapter calls this before handing the request
        to FastAPI. Missing bindings leave local/default values unchanged.
        """
        text_bindings = {
            "SUPABASE_URL": "supabase_url",
            "SUPABASE_SERVICE_ROLE_KEY": "supabase_service_key",
            "OPENROUTER_API_KEY": "openrouter_api_key",
            "OPENROUTER_BASE_URL": "openrouter_base_url",
            "OPENROUTER_MODEL": "openrouter_model",
            "CORS_ALLOW_ORIGINS": "cors_allow_origins",
        }
        for binding_name, attribute_name in text_bindings.items():
            value = _worker_binding(env, binding_name)
            if value is not None:
                if attribute_name in {"supabase_url", "openrouter_base_url"}:
                    value = value.rstrip("/")
                setattr(self, attribute_name, value)

        numeric_bindings: dict[str, tuple[str, type[int | float]]] = {
            "LLM_TEMPERATURE": ("llm_temperature", float),
            "LLM_SEED": ("llm_seed", int),
            "LLM_TIMEOUT_SECONDS": ("llm_timeout_seconds", float),
            "EVAL_CONCURRENCY": ("eval_concurrency", int),
            "MAX_FEW_SHOT_EXAMPLES": ("max_few_shot_examples", int),
        }
        for binding_name, (attribute_name, converter) in numeric_bindings.items():
            value = _worker_binding(env, binding_name)
            if value is None:
                continue
            try:
                setattr(self, attribute_name, converter(value))
            except ValueError:
                # Match local .env parsing: malformed optional values fall back
                # to the value already loaded into the settings object.
                continue


settings = Settings()
