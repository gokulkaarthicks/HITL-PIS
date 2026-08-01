"""Bug report endpoints: list, create, run the LLM, save a human correction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..db import SupabaseClient, get_db
from ..llm import classify
from ..prompt_service import get_active_prompt
from ..schemas import CorrectionRequest, CreateBugRequest, RunRequest

router = APIRouter(tags=["bugs"])

BUG_COLUMNS = (
    "id,report_text,source,llm_output_json,human_corrected_json,status,"
    "prompt_version_used,reviewer_id,created_at,llm_run_at,reviewed_at,"
    "last_updated_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_llm(request: Request) -> httpx.AsyncClient:
    return request.app.state.llm_client


async def _load_bug(db: SupabaseClient, bug_id: str) -> dict[str, Any]:
    bug = await db.select_one(
        "bug_reports", columns=BUG_COLUMNS, filters={"id": f"eq.{bug_id}"}
    )
    if bug is None:
        raise HTTPException(status_code=404, detail=f"Bug report {bug_id} not found")
    return bug


@router.get("/bugs")
async def list_bugs(db: SupabaseClient = Depends(get_db)) -> list[dict[str, Any]]:
    return await db.select(
        "bug_reports", columns=BUG_COLUMNS, order="created_at.desc"
    )


@router.post("/bugs", status_code=201)
async def create_bug(
    payload: CreateBugRequest, db: SupabaseClient = Depends(get_db)
) -> dict[str, Any]:
    created = await db.insert(
        "bug_reports",
        {"report_text": payload.report_text, "source": "manual", "status": "new"},
    )
    if not created:
        raise HTTPException(status_code=502, detail="Failed to create the bug report")
    return created[0]


@router.post("/bugs/{bug_id}/run")
async def run_llm(
    bug_id: str,
    payload: RunRequest | None = None,
    db: SupabaseClient = Depends(get_db),
    llm_client: httpx.AsyncClient = Depends(get_llm),
) -> dict[str, Any]:
    """Classify one bug report with the currently active prompt."""
    bug = await _load_bug(db, bug_id)
    prompt = await get_active_prompt(db)

    triage = await classify(llm_client, bug["report_text"], prompt["prompt_text"])

    # Re-running keeps an existing human correction (and therefore the reviewed
    # status); it only refreshes what the model said.
    already_reviewed = bug.get("human_corrected_json") is not None
    updates: dict[str, Any] = {
        "llm_output_json": triage.model_dump(),
        "status": "reviewed" if already_reviewed else "llm_run",
        "prompt_version_used": prompt["id"],
        "llm_run_at": _now(),
        "last_updated_at": _now(),
    }
    if payload and payload.reviewer_id:
        updates["reviewer_id"] = payload.reviewer_id

    updated = await db.update(
        "bug_reports", updates, filters={"id": f"eq.{bug_id}"}
    )
    if not updated:
        raise HTTPException(status_code=502, detail="Failed to save the LLM output")
    return updated[0]


@router.put("/bugs/{bug_id}/correction")
async def save_correction(
    bug_id: str,
    payload: CorrectionRequest,
    db: SupabaseClient = Depends(get_db),
) -> dict[str, Any]:
    """Persist a reviewer's corrected triage plus an audit event."""
    bug = await _load_bug(db, bug_id)
    corrected = payload.corrected.model_dump()

    # The audit trail records what the correction replaced: a previous human
    # correction if there was one, otherwise the model's own output.
    previous = bug.get("human_corrected_json") or bug.get("llm_output_json")

    await db.insert(
        "review_events",
        {
            "bug_report_id": bug_id,
            "old_output_json": previous,
            "new_output_json": corrected,
            "reviewer_id": payload.reviewer_id,
        },
    )

    updated = await db.update(
        "bug_reports",
        {
            "human_corrected_json": corrected,
            "status": "reviewed",
            "reviewer_id": payload.reviewer_id,
            "reviewed_at": _now(),
            "last_updated_at": _now(),
        },
        filters={"id": f"eq.{bug_id}"},
    )
    if not updated:
        raise HTTPException(status_code=502, detail="Failed to save the correction")
    return updated[0]
