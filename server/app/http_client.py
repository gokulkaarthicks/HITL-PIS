"""Outbound HTTP client for CPython and Cloudflare Python Workers."""

from __future__ import annotations

import json as jsonlib
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

import httpx


class OutboundHTTPError(RuntimeError):
    """Raised when an outbound request cannot be completed."""


@dataclass(frozen=True)
class WorkerHTTPResponse:
    status_code: int
    text: str

    @property
    def content(self) -> bytes:
        return self.text.encode()

    def json(self) -> Any:
        return jsonlib.loads(self.text)


class AsyncHTTPClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...

    async def post(self, url: str, **kwargs: Any) -> Any: ...

    async def aclose(self) -> None: ...


async def _worker_fetch(url: str, **options: Any) -> Any:
    # The workers package imports JavaScript modules that exist only in the
    # Cloudflare/Pyodide runtime, so keep this import off the local path.
    from workers import fetch

    return await fetch(url, **options)


class OutboundHTTPClient:
    """The small AsyncClient subset used by Supabase and OpenRouter."""

    def __init__(
        self,
        *,
        timeout: float,
        headers: Mapping[str, str] | None = None,
        force_worker_transport: bool = False,
    ) -> None:
        self._default_headers = dict(headers or {})
        self._uses_worker_fetch = force_worker_transport or sys.platform == "emscripten"
        self._httpx = (
            None
            if self._uses_worker_fetch
            else httpx.AsyncClient(
                timeout=httpx.Timeout(timeout), headers=self._default_headers
            )
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if self._httpx is not None:
            request_options: dict[str, Any] = {
                "params": params,
                "json": json,
                "headers": headers,
            }
            if timeout is not None:
                request_options["timeout"] = timeout
            try:
                return await self._httpx.request(
                    method,
                    url,
                    **request_options,
                )
            except httpx.HTTPError as exc:
                raise OutboundHTTPError(str(exc)) from exc

        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params, doseq=True)}"

        merged_headers = {**self._default_headers, **dict(headers or {})}
        options: dict[str, Any] = {"method": method, "headers": merged_headers}
        if json is not None:
            merged_headers.setdefault("Content-Type", "application/json")
            options["body"] = jsonlib.dumps(json)

        try:
            response = await _worker_fetch(url, **options)
            response_text = await response.text()
        except (OSError, RuntimeError) as exc:
            raise OutboundHTTPError(str(exc)) from exc
        return WorkerHTTPResponse(int(response.status), response_text)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        if self._httpx is not None:
            await self._httpx.aclose()
