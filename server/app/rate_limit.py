"""Pure routing rules for Cloudflare's expensive-endpoint rate limits."""

from __future__ import annotations

import re
from typing import Literal

RateLimitBucket = Literal["triage", "evaluation"]

_TRIAGE_ROUTE = re.compile(r"^/bugs/[^/]+/run$")
_EVALUATION_ROUTES = {"/eval/run", "/eval/run/stream"}


def rate_limit_bucket(method: str, path: str) -> RateLimitBucket | None:
    """Return the rate-limit bucket for an LLM-triggering request."""
    if method.upper() != "POST":
        return None
    if _TRIAGE_ROUTE.fullmatch(path):
        return "triage"
    if path in _EVALUATION_ROUTES:
        return "evaluation"
    return None
