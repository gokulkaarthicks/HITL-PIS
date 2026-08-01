"""Cloudflare Python Worker entrypoint for the existing FastAPI application."""

import asgi
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from server.app.config import settings
from server.app.main import app
from server.app.rate_limit import rate_limit_bucket


def _rate_limited_response(request):
    headers = {"Retry-After": "60"}
    origin = request.headers.get("Origin")
    if origin in settings.allowed_origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return Response.json(
        {"detail": "Too many LLM requests. Try again in one minute."},
        status=429,
        headers=headers,
    )


async def _within_rate_limit(env, request) -> bool:
    bucket = rate_limit_bucket(request.method, urlparse(request.url).path)
    if bucket is None:
        return True

    # Per-IP limits are acceptable for this small public demo. The generous
    # thresholds leave room for all 93 reports while containing obvious abuse.
    key = request.headers.get("CF-Connecting-IP") or "unknown"
    limiter = (
        env.TRIAGE_RATE_LIMITER
        if bucket == "triage"
        else env.EVALUATION_RATE_LIMITER
    )
    result = await limiter.limit({"key": key})
    return bool(result.get("success") if isinstance(result, dict) else result.success)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        settings.bind_worker_env(self.env)
        if not await _within_rate_limit(self.env, request):
            return _rate_limited_response(request)
        return await asgi.fetch(app, request, self.env)
