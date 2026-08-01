"""Evaluation endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from ..db import SupabaseClient, get_db
from ..evaluation import get_latest_evaluation, run_evaluation
from ..http_client import AsyncHTTPClient
from ..schemas import EvalComparison
from .bugs import get_llm

logger = logging.getLogger("hitl")

router = APIRouter(prefix="/eval", tags=["evaluation"])

FORCE_DESCRIPTION = (
    "Re-score the previous prompt version instead of reusing its stored run. "
    "Needed after changing the model or decoding settings."
)


@router.get("/examples")
async def list_examples(db: SupabaseClient = Depends(get_db)) -> list[dict[str, Any]]:
    return await db.select("evaluation_examples", order="id.asc")


@router.post("/run")
async def post_run(
    force: bool = Query(default=False, description=FORCE_DESCRIPTION),
    db: SupabaseClient = Depends(get_db),
    llm_client: AsyncHTTPClient = Depends(get_llm),
) -> EvalComparison:
    return await run_evaluation(db, llm_client, force=force)


@router.post("/run/stream")
async def post_run_stream(
    force: bool = Query(default=False, description=FORCE_DESCRIPTION),
    db: SupabaseClient = Depends(get_db),
    llm_client: AsyncHTTPClient = Depends(get_llm),
) -> StreamingResponse:
    """Same evaluation as POST /eval/run, streamed as newline-delimited JSON.

    Emits `{"type": "progress", ...}` per completed example and closes with a
    single `{"type": "result", ...}` or `{"type": "error", ...}` line. The work
    is identical -- `run_evaluation` just receives a progress callback -- so
    there is one implementation, not two.
    """

    async def generate() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_progress(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def work() -> None:
            try:
                result = await run_evaluation(
                    db, llm_client, force=force, on_progress=on_progress
                )
                await queue.put({"type": "result", "result": result.model_dump()})
            except Exception as exc:  # surfaced to the client as a final line
                logger.warning("Streamed evaluation failed: %s", exc)
                await queue.put({"type": "error", "detail": str(exc)})
            finally:
                await queue.put(None)  # sentinel: no more events

        task = asyncio.create_task(work())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event) + "\n"
        finally:
            # Client disconnected mid-run: stop the work rather than leaving it
            # to finish against a socket nobody is reading.
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/latest")
async def get_latest(
    response: Response, db: SupabaseClient = Depends(get_db)
) -> EvalComparison | None:
    """Latest stored comparison, or 204 when no evaluation has ever run."""
    latest = await get_latest_evaluation(db)
    if latest is None:
        response.status_code = 204
        return None
    return latest
