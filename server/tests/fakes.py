"""In-memory stand-ins for Supabase and the LLM, used by the loop tests.

FakeSupabase implements just enough of the PostgREST surface that `db.py`
exposes: the `eq.` and `is.true` filters, `column.asc|desc` ordering and limit.
Keeping it small is deliberate -- it should fail loudly on a filter form the
real code does not actually use.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

Row = dict[str, Any]


class FakeSupabase:
    def __init__(self, tables: dict[str, list[Row]] | None = None) -> None:
        self.tables: dict[str, list[Row]] = tables or {}
        self._ids = itertools.count(1)
        # Start from real "now" so inserted rows are always newer than seeded
        # fixtures, matching Postgres `default now()`. A fixed past epoch here
        # silently backdates inserts relative to seed data, which has twice
        # produced misleading ordering results.
        self._clock = datetime.now(timezone.utc)

    def _next_timestamp(self) -> str:
        self._clock += timedelta(seconds=1)
        return self._clock.isoformat()

    @staticmethod
    def _matches(row: Row, column: str, expression: str) -> bool:
        if expression.startswith("eq."):
            return str(row.get(column)) == expression[3:]
        if expression == "is.true":
            return row.get(column) is True
        if expression == "is.false":
            return row.get(column) is False
        raise AssertionError(f"FakeSupabase does not support filter {expression!r}")

    def _filtered(self, table: str, filters: dict[str, str] | None) -> list[Row]:
        rows = self.tables.setdefault(table, [])
        if not filters:
            return list(rows)
        return [
            row
            for row in rows
            if all(self._matches(row, col, expr) for col, expr in filters.items())
        ]

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[Row]:
        rows = self._filtered(table, filters)
        if order:
            # PostgREST accepts comma-separated keys ("created_at.desc,name.desc").
            # Sorting by each key from last to first, with a stable sort, gives
            # the same result as a single multi-key comparison.
            for spec in reversed([s for s in order.split(",") if s]):
                column, _, direction = spec.partition(".")
                rows.sort(
                    key=lambda r, c=column: str(r.get(c) or ""),
                    reverse=direction.startswith("desc"),
                )
        if limit is not None:
            rows = rows[:limit]
        return [dict(r) for r in rows]

    async def select_one(
        self, table: str, *, columns: str = "*", filters: dict[str, str]
    ) -> Row | None:
        rows = await self.select(table, columns=columns, filters=filters, limit=1)
        return rows[0] if rows else None

    async def insert(self, table: str, rows: Row | list[Row]) -> list[Row]:
        payload = list(rows) if isinstance(rows, (list, tuple)) else [rows]
        stored = []
        for row in payload:
            record = dict(row)
            record.setdefault("id", f"{table}-{next(self._ids)}")
            record.setdefault("created_at", self._next_timestamp())
            self.tables.setdefault(table, []).append(record)
            stored.append(dict(record))
        return stored

    async def update(
        self, table: str, values: Row, *, filters: dict[str, str]
    ) -> list[Row]:
        updated = []
        for row in self.tables.setdefault(table, []):
            if all(self._matches(row, col, expr) for col, expr in filters.items()):
                row.update(values)
                updated.append(dict(row))
        return updated
