"""Administrative operation for restoring the public demo."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..db import SupabaseClient, get_db
from ..schemas import ResetDemoRequest

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset")
async def reset_demo(
    payload: ResetDemoRequest,
    db: SupabaseClient = Depends(get_db),
) -> dict[str, Any]:
    """Transactionally restore the seeded application state."""
    results = await db.rpc("reset_demo")
    if not results:
        raise HTTPException(status_code=502, detail="Database reset returned no result")
    return results[0]
