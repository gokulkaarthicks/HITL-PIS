"""Prompt version endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..db import SupabaseClient, SupabaseError, get_db
from ..prompt_service import (
    fetch_corrections,
    get_active_prompt,
    get_candidate_prompt,
    improve_prompt,
    is_candidate_schema_missing,
    list_prompts,
    PromptServiceError,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
async def get_prompts(db: SupabaseClient = Depends(get_db)) -> list[dict[str, Any]]:
    return await list_prompts(db)


@router.get("/active")
async def get_active(db: SupabaseClient = Depends(get_db)) -> dict[str, Any]:
    prompt = await get_active_prompt(db)
    # Surface review signal and the candidate gate state in one UI read.
    prompt["available_corrections_count"] = len(await fetch_corrections(db))
    try:
        prompt["pending_candidate"] = await get_candidate_prompt(db)
        prompt["schema_upgrade_required"] = False
    except PromptServiceError as exc:
        cause = exc.__cause__
        if not isinstance(cause, SupabaseError) or not is_candidate_schema_missing(
            cause
        ):
            raise
        # Keep the existing application readable while making the unavailable
        # candidate workflow explicit. Mutations remain blocked until migrated.
        prompt["pending_candidate"] = None
        prompt["schema_upgrade_required"] = True
    return prompt


@router.post("/improve", status_code=201)
async def improve(db: SupabaseClient = Depends(get_db)) -> dict[str, Any]:
    return await improve_prompt(db)
