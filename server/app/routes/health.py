"""Liveness and configuration check.

Reports whether each credential is present as a boolean. It never echoes a
secret value.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    missing = settings.missing()
    return {
        "status": "ok" if not missing else "misconfigured",
        "model": settings.openrouter_model,
        "configured": {
            "supabase_url": bool(settings.supabase_url),
            "supabase_service_role_key": bool(settings.supabase_service_key),
            "openrouter_api_key": bool(settings.openrouter_api_key),
        },
        "missing_env": missing,
    }
