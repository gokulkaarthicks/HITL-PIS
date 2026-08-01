from app.rate_limit import rate_limit_bucket


def test_llm_routes_are_assigned_to_separate_rate_limit_buckets() -> None:
    assert rate_limit_bucket("POST", "/bugs/abc-123/run") == "triage"
    assert rate_limit_bucket("POST", "/eval/run") == "evaluation"
    assert rate_limit_bucket("POST", "/eval/run/stream") == "evaluation"


def test_non_llm_routes_are_not_rate_limited() -> None:
    assert rate_limit_bucket("GET", "/bugs/abc-123/run") is None
    assert rate_limit_bucket("GET", "/bugs") is None
    assert rate_limit_bucket("POST", "/prompts/improve") is None
    assert rate_limit_bucket("POST", "/admin/reset") is None
