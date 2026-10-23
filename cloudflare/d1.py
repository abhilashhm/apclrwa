"""Small async D1 storage adapter used by the Cloudflare Worker.

The adapter deliberately exposes only the operations required by the Worker
routes.  It does not pretend that D1 is a synchronous sqlite3 connection:
reads are awaited and multi-statement writes use D1 batch transactions.
"""

from __future__ import annotations

import json
from typing import Any, Iterable


class D1Error(RuntimeError):
    """Unexpected D1 failure."""


class D1Conflict(D1Error):
    """Optimistic-concurrency or uniqueness conflict."""


def _plain(value: Any) -> Any:
    """Convert Workers FFI wrapper values to ordinary Python values."""
    if value is None:
        return None
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        return to_py()
    return value


def _results(value: Any) -> list[dict[str, Any]]:
    value = _plain(value)
    if value is None:
        return []
    if isinstance(value, list):
        return [dict(row) if isinstance(row, dict) else row for row in value]
    rows = getattr(value, "results", None)
    if rows is not None:
        rows = _plain(rows)
        return [dict(row) if isinstance(row, dict) else row for row in (rows or [])]
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        return [dict(row) if isinstance(row, dict) else row for row in value["results"]]
    return []


class D1Store:
    """D1 binding wrapper with JSON collection versioning and CAS writes."""

    CHUNK_BYTES = 1_500_000

    def __init__(self, database: Any):
        self.database = database

    def statement(self, sql: str, *parameters: Any) -> Any:
        statement = self.database.prepare(sql)
        return statement.bind(*parameters) if parameters else statement

    async def first(self, sql: str, *parameters: Any) -> dict[str, Any] | None:
        try:
            value = await self.statement(sql, *parameters).first()
        except Exception as exc:  # Workers exceptions are runtime-specific.
            raise D1Error(str(exc)) from exc
        value = _plain(value)
        return dict(value) if isinstance(value, dict) else value

    async def all(self, sql: str, *parameters: Any) -> list[dict[str, Any]]:
        try:
            value = await self.statement(sql, *parameters).all()
        except Exception as exc:
            raise D1Error(str(exc)) from exc
        return _results(value)

    async def run(self, sql: str, *parameters: Any) -> Any:
        try:
            return _plain(await self.statement(sql, *parameters).run())
        except Exception as exc:
            raise D1Error(str(exc)) from exc

    async def batch(self, statements: Iterable[tuple[str, tuple[Any, ...]]]) -> Any:
        prepared = [self.statement(sql, *parameters) for sql, parameters in statements]
        try:
            return _plain(await self.database.batch(prepared))
        except Exception as exc:
            message = str(exc)
            if (
                "portal revision conflict" in message.lower()
                or "auth rate limit" in message.lower()
                or "unique constraint" in message.lower()
                or "constraint failed" in message.lower()
                or "accounting period is closed" in message.lower()
                or "journal entry is immutable" in message.lower()
                or "journal entry lines are immutable" in message.lower()
            ):
                raise D1Conflict(message) from exc
            raise D1Error(message) from exc

    async def ping(self) -> None:
        await self.first("SELECT 1 AS ok")

    @staticmethod
    def _chunks(value: Any) -> list[str]:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode("utf-8")) <= D1Store.CHUNK_BYTES:
            return [encoded]
        if not isinstance(value, list):
            raise D1Error("A scalar portal collection exceeds the D1 row limit.")
        chunks: list[str] = []
        current: list[Any] = []
        for item in value:
            candidate = json.dumps([*current, item], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
            if current and len(candidate.encode("utf-8")) > D1Store.CHUNK_BYTES:
                chunks.append(json.dumps(current, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True))
                current = [item]
            else:
                current.append(item)
        if current or not chunks:
            chunks.append(json.dumps(current, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True))
        return chunks

    async def ensure_portal(self, defaults: dict[str, Any], now: str) -> None:
        state = await self.first("SELECT id FROM portal_state WHERE id = 1")
        if state is not None:
            return
        statements: list[tuple[str, tuple[Any, ...]]] = [
            ("INSERT OR IGNORE INTO portal_state(id, revision, updated_at) VALUES (1, 0, ?)", (now,)),
        ]
        for name, value in defaults.items():
            version_id = "initial"
            chunks = self._chunks(value)
            statements.append((
                "INSERT OR IGNORE INTO portal_collection_versions(name, version_id, updated_at) VALUES (?, ?, ?)",
                (name, version_id, now),
            ))
            for chunk_no, chunk in enumerate(chunks):
                statements.append((
                    "INSERT OR IGNORE INTO portal_collection_chunks(name, version_id, chunk_no, value_json) VALUES (?, ?, ?, ?)",
                    (name, version_id, chunk_no, chunk),
                ))
        try:
            await self.batch(statements)
        except D1Conflict:
            # Another request seeded the singleton while this request was
            # preparing its seed. The next read is authoritative.
            return

    async def load_portal(self, defaults: dict[str, Any], now: str) -> tuple[int, dict[str, Any]]:
        await self.ensure_portal(defaults, now)
        state = await self.first("SELECT revision FROM portal_state WHERE id = 1")
        if state is None:
            raise D1Error("Portal storage has not been initialized.")
        rows = await self.all(
            """
            SELECT v.name, c.chunk_no, c.value_json
            FROM portal_collection_versions v
            JOIN portal_collection_chunks c ON c.name = v.name AND c.version_id = v.version_id
            ORDER BY v.name, c.chunk_no
            """
        )
        values: dict[str, Any] = {}
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(str(row["name"]), []).append(str(row["value_json"]))
        for name, fallback in defaults.items():
            pieces = grouped.get(name)
            if not pieces:
                values[name] = fallback
                continue
            decoded = [json.loads(piece) for piece in pieces]
            values[name] = [item for piece in decoded for item in piece] if isinstance(decoded[0], list) else decoded[0]
        return int(state["revision"]), values

    def save_statements(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        revision: int,
        now: str,
        *,
        force: bool = False,
        extra_statements: Iterable[tuple[str, tuple[Any, ...]]] = (),
    ) -> tuple[list[tuple[str, tuple[Any, ...]]], int]:
        changed = [name for name in old if old[name] != new[name]]
        if not changed and not force:
            return [], revision
        statements: list[tuple[str, tuple[Any, ...]]] = [
            ("DELETE FROM portal_revision_guard WHERE id = 1", ()),
            ("INSERT INTO portal_revision_guard(id, expected_revision) VALUES (1, ?)", (revision,)),
        ]
        for statement in extra_statements:
            statements.append(statement)
        next_revision = revision + 1
        statements.append((
            "UPDATE portal_state SET revision = ?, updated_at = ? WHERE id = 1",
            (next_revision, now),
        ))
        for name in changed:
            version_id = f"v{next_revision}-{name}"
            statements.append((
                "INSERT INTO portal_collection_versions(name, version_id, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET version_id = excluded.version_id, updated_at = excluded.updated_at",
                (name, version_id, now),
            ))
            for chunk_no, chunk in enumerate(self._chunks(new[name])):
                statements.append((
                    "INSERT INTO portal_collection_chunks(name, version_id, chunk_no, value_json) VALUES (?, ?, ?, ?)",
                    (name, version_id, chunk_no, chunk),
                ))
            statements.append((
                "DELETE FROM portal_collection_chunks WHERE name = ? AND version_id <> ?",
                (name, version_id),
            ))
        statements.append(("DELETE FROM portal_revision_guard WHERE id = 1", ()))
        return statements, next_revision

    async def save_portal(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        revision: int,
        now: str,
        *,
        force: bool = False,
        extra_statements: Iterable[tuple[str, tuple[Any, ...]]] = (),
    ) -> int:
        statements, next_revision = self.save_statements(old, new, revision, now, force=force, extra_statements=extra_statements)
        if statements:
            await self.batch(statements)
        return next_revision
