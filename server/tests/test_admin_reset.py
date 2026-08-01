from pathlib import Path

import httpx
import pytest

from app.db import get_db
from app.main import app


SCHEMA_SQL = Path(__file__).parents[2] / "supabase" / "schema.sql"


class FakeResetDB:
    def __init__(self) -> None:
        self.calls = []

    async def rpc(self, function_name, arguments=None):
        self.calls.append((function_name, arguments))
        return [
            {
                "status": "reset",
                "seeded_bug_count": 93,
                "deleted_manual_count": 2,
                "active_prompt": "v1-baseline",
            }
        ]


@pytest.mark.asyncio
async def test_reset_rejects_wrong_confirmation_without_touching_database() -> None:
    db = FakeResetDB()
    app.dependency_overrides[get_db] = lambda: db

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/reset",
                json={"confirmation": "reset"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert db.calls == []


@pytest.mark.asyncio
async def test_reset_calls_atomic_database_rpc_after_confirmation() -> None:
    db = FakeResetDB()
    app.dependency_overrides[get_db] = lambda: db

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/reset",
                json={"confirmation": "RESET"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["seeded_bug_count"] == 93
    assert db.calls == [("reset_demo", None)]


def test_reset_rpc_uses_safe_full_table_deletes() -> None:
    schema = SCHEMA_SQL.read_text()
    reset_function = schema.split(
        "create or replace function public.reset_demo()", 1
    )[1].split("revoke all on function public.reset_demo()", 1)[0]

    assert "delete from evaluation_runs where true;" in reset_function
    assert "delete from review_events where true;" in reset_function
