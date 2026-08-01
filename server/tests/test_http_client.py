from __future__ import annotations

import json
import inspect

import pytest

from app import http_client as http_client_module
from app.http_client import OutboundHTTPClient
from app.db import get_db
from app.routes.bugs import get_llm


class FakeFetchResponse:
    status = 201

    async def text(self) -> str:
        return '{"created": true}'


def test_worker_dependencies_are_async_to_avoid_fastapi_thread_pool():
    assert inspect.iscoroutinefunction(get_db)
    assert inspect.iscoroutinefunction(get_llm)


@pytest.mark.asyncio
async def test_worker_transport_uses_fetch_with_query_headers_and_json(monkeypatch):
    captured = {}

    async def fake_fetch(url, **options):
        captured["url"] = url
        captured["options"] = options
        return FakeFetchResponse()

    monkeypatch.setattr(http_client_module, "_worker_fetch", fake_fetch)
    client = OutboundHTTPClient(
        timeout=5,
        headers={"Authorization": "Bearer secret"},
        force_worker_transport=True,
    )
    response = await client.request(
        "POST",
        "https://example.test/items",
        params={"select": "id,name", "id": "eq.1"},
        json={"name": "example"},
        headers={"Prefer": "return=representation"},
    )

    assert captured["url"] == (
        "https://example.test/items?select=id%2Cname&id=eq.1"
    )
    assert captured["options"]["headers"] == {
        "Authorization": "Bearer secret",
        "Prefer": "return=representation",
        "Content-Type": "application/json",
    }
    assert json.loads(captured["options"]["body"]) == {"name": "example"}
    assert response.status_code == 201
    assert response.json() == {"created": True}


@pytest.mark.asyncio
async def test_worker_transport_omits_body_for_get(monkeypatch):
    captured = {}

    async def fake_fetch(_url, **options):
        captured.update(options)
        return FakeFetchResponse()

    monkeypatch.setattr(http_client_module, "_worker_fetch", fake_fetch)
    client = OutboundHTTPClient(timeout=5, force_worker_transport=True)
    await client.request("GET", "https://example.test/items")

    assert "body" not in captured
