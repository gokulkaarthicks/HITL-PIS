"""Prompt version endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..db import SupabaseClient, get_db
from ..prompt_service import (
    fetch_corrections,
    get_active_prompt,
    improve_prompt,
    list_prompts,
)
router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
async def get_prompts(db: SupabaseClient = Depends(get_db)) -> list[dict[str, Any]]:
    return await list_prompts(db)


@router.get("/active")
async def get_active(db: SupabaseClient = Depends(get_db)) -> dict[str, Any]:
    prompt = await get_active_prompt(db)
    # Surfaced so the UI can enable/disable "Improve Prompt" and show how much
    # review signal is currently available.
    prompt["available_corrections_count"] = len(await fetch_corrections(db))
    return prompt


@router.post("/improve", status_code=201)
async def improve(db: SupabaseClient = Depends(get_db)) -> dict[str, Any]:
    return await improve_prompt(db)
