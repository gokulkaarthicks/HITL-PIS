from types import SimpleNamespace

from app.config import Settings


def test_worker_bindings_override_runtime_settings() -> None:
    settings = Settings()
    env = SimpleNamespace(
        SUPABASE_URL="https://example.supabase.co/",
        SUPABASE_SERVICE_ROLE_KEY="service-key",
        OPENROUTER_API_KEY="openrouter-key",
        OPENROUTER_MODEL="example/free-model",
        LLM_TIMEOUT_SECONDS="12.5",
        EVAL_CONCURRENCY="3",
        CORS_ALLOW_ORIGINS="https://app.pages.dev,http://localhost:5173",
    )

    settings.bind_worker_env(env)

    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_service_key == "service-key"
    assert settings.openrouter_api_key == "openrouter-key"
    assert settings.openrouter_model == "example/free-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.eval_concurrency == 3
    assert settings.allowed_origins == [
        "https://app.pages.dev",
        "http://localhost:5173",
    ]


def test_missing_and_invalid_worker_bindings_keep_existing_values() -> None:
    settings = Settings(eval_concurrency=4, llm_seed=7)

    settings.bind_worker_env(SimpleNamespace(EVAL_CONCURRENCY="invalid"))

    assert settings.eval_concurrency == 4
    assert settings.llm_seed == 7
