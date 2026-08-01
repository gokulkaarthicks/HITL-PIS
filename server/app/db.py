"""Minimal async Supabase (PostgREST) client.

We talk to Supabase over its REST interface rather than a Postgres wire-protocol
driver because the deployment target (Cloudflare Workers) cannot open raw TCP
sockets. HTTP works identically locally and on Workers.

Only the four verbs this app actually needs are implemented. Filters are passed
as PostgREST operator strings (``{"id": "eq.<uuid>"}``) so callers stay explicit
about matching semantics.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .config import settings
from .http_client import OutboundHTTPClient, OutboundHTTPError

Row = dict[str, Any]


class SupabaseError(RuntimeError):
    """Raised when PostgREST returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Supabase request failed ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class SupabaseClient:
    def __init__(self, url: str, service_key: str) -> None:
        self._rest_url = f"{url}/rest/v1"
        self._client = OutboundHTTPClient(
            timeout=30.0,
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        table: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        prefer: str | None = None,
    ) -> list[Row]:
        headers = {"Prefer": prefer} if prefer else None
        try:
            response = await self._client.request(
                method,
                f"{self._rest_url}/{table}",
                params=params,
                json=json,
                headers=headers,
            )
        except OutboundHTTPError as exc:
            raise SupabaseError(502, f"Could not reach Supabase: {exc}") from exc
        if response.status_code >= 400:
            raise SupabaseError(response.status_code, response.text)
        if not response.content:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else [payload]

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[Row]:
        params: dict[str, Any] = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        return await self._request("GET", table, params=params)

    async def select_one(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, str],
    ) -> Row | None:
        rows = await self.select(table, columns=columns, filters=filters, limit=1)
        return rows[0] if rows else None

    async def insert(
        self, table: str, rows: Row | Sequence[Row]
    ) -> list[Row]:
        payload = list(rows) if isinstance(rows, (list, tuple)) else [rows]
        if not payload:
            return []
        return await self._request(
            "POST", table, json=payload, prefer="return=representation"
        )

    async def update(
        self, table: str, values: Row, *, filters: Mapping[str, str]
    ) -> list[Row]:
        return await self._request(
            "PATCH",
            table,
            params=dict(filters),
            json=values,
            prefer="return=representation",
        )


_client: SupabaseClient | None = None


async def get_db() -> SupabaseClient:
    """Return the process-wide client, creating it on first use."""
    global _client
    if _client is None:
        missing = settings.missing()
        if "SUPABASE_URL" in missing or "SUPABASE_SERVICE_ROLE_KEY" in missing:
            raise RuntimeError(
                "Supabase is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY (see server/.env.example)."
            )
        _client = SupabaseClient(settings.supabase_url, settings.supabase_service_key)
    return _client


async def close_db() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
