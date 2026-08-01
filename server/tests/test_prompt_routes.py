import httpx
import pytest

from app.db import SupabaseError, get_db
from app.main import app


class OutdatedPromptSchemaDB:
    async def select_one(self, table, *, columns="*", filters):
        if filters == {"is_active": "is.true"}:
            return {
                "id": "p1",
                "version_name": "v1-baseline",
                "prompt_text": "baseline",
                "is_active": True,
                "created_from_corrections_count": 0,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        if filters == {"lifecycle_status": "eq.candidate"}:
            raise SupabaseError(
                400,
                '{"code":"42703","message":"column '
                'prompt_versions.lifecycle_status does not exist"}',
            )
        raise AssertionError(f"Unexpected select_one filters: {filters}")

    async def select(self, table, *, columns="*", filters=None, order=None, limit=None):
        if table == "bug_reports":
            return []
        raise AssertionError(f"Unexpected select: {table}")


@pytest.mark.asyncio
async def test_active_prompt_stays_readable_when_candidate_migration_is_missing():
    app.dependency_overrides[get_db] = lambda: OutdatedPromptSchemaDB()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/prompts/active")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["version_name"] == "v1-baseline"
    assert response.json()["pending_candidate"] is None
    assert response.json()["schema_upgrade_required"] is True


@pytest.mark.asyncio
async def test_candidate_creation_explains_missing_database_migration():
    app.dependency_overrides[get_db] = lambda: OutdatedPromptSchemaDB()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/prompts/improve")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "apply supabase/schema.sql" in response.json()["detail"]
