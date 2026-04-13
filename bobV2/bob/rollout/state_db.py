from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    path        TEXT NOT NULL,
    model       TEXT,
    cwd         TEXT,
    preview     TEXT,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_created ON threads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_updated ON threads(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_name    ON threads(name);

CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    context     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ThreadRecord:
    """Plain-data container for a thread row."""

    __slots__ = ("id", "name", "path", "model", "cwd", "preview", "turn_count", "created_at", "updated_at")

    def __init__(
        self,
        id: str,
        name: Optional[str],
        path: str,
        model: Optional[str],
        cwd: Optional[str],
        preview: Optional[str],
        turn_count: int,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.id = id
        self.name = name
        self.path = path
        self.model = model
        self.cwd = cwd
        self.preview = preview
        self.turn_count = int(turn_count or 0)
        self.created_at = created_at
        self.updated_at = updated_at

    def __repr__(self) -> str:
        return (
            f"ThreadRecord(id={self.id!r}, name={self.name!r}, "
            f"model={self.model!r}, cwd={self.cwd!r})"
        )


class StateDb:
    """
    Async SQLite state database for bob threads and memories.

    Usage::

        db = StateDb(Path("~/.bob/state.db").expanduser())
        await db.connect()
        try:
            await db.upsert_thread(...)
        finally:
            await db.close()
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open (and initialise) the database."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        # Lightweight migration for older databases.
        await self._ensure_threads_columns()
        await self._conn.commit()

    async def _ensure_threads_columns(self) -> None:
        assert self._conn is not None, "StateDb not connected"
        cur = await self._conn.execute("PRAGMA table_info(threads)")
        rows = await cur.fetchall()
        existing = {str(r["name"]) for r in rows}
        if "preview" not in existing:
            await self._conn.execute("ALTER TABLE threads ADD COLUMN preview TEXT")
        if "turn_count" not in existing:
            await self._conn.execute("ALTER TABLE threads ADD COLUMN turn_count INTEGER NOT NULL DEFAULT 0")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "StateDb":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Thread operations
    # ------------------------------------------------------------------

    async def upsert_thread(
        self,
        id: str,
        name: Optional[str],
        path: str,
        model: Optional[str],
        cwd: Optional[str],
    ) -> None:
        """Insert or update a thread record."""
        assert self._conn is not None, "StateDb not connected"
        now = _now_iso()
        await self._conn.execute(
            """
            INSERT INTO threads (id, name, path, model, cwd, preview, turn_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name       = COALESCE(excluded.name, threads.name),
                path       = excluded.path,
                model      = excluded.model,
                cwd        = excluded.cwd,
                updated_at = excluded.updated_at
            """,
            (id, name, path, model, cwd, None, 0, now, now),
        )
        await self._conn.commit()

    async def update_thread_name(self, id: str, name: str) -> None:
        """Rename an existing thread."""
        assert self._conn is not None, "StateDb not connected"
        now = _now_iso()
        await self._conn.execute(
            "UPDATE threads SET name = ?, updated_at = ? WHERE id = ?",
            (name, now, id),
        )
        await self._conn.commit()

    async def list_threads(
        self,
        limit: int = 25,
        offset: int = 0,
        cwd_filter: Optional[str] = None,
        sort_by: str = "updated_at",
    ) -> list[ThreadRecord]:
        """Return threads ordered by creation time (newest first)."""
        assert self._conn is not None, "StateDb not connected"
        order_col = "updated_at" if sort_by == "updated_at" else "created_at"
        if cwd_filter is not None:
            cursor = await self._conn.execute(
                f"SELECT * FROM threads WHERE cwd = ? ORDER BY {order_col} DESC LIMIT ? OFFSET ?",
                (cwd_filter, limit, offset),
            )
        else:
            cursor = await self._conn.execute(
                f"SELECT * FROM threads ORDER BY {order_col} DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [ThreadRecord(**dict(r)) for r in rows]

    async def touch_thread_activity(
        self,
        id: str,
        *,
        preview: Optional[str] = None,
        increment_turn_count: bool = False,
    ) -> None:
        """Update thread freshness metadata after a completed turn."""
        assert self._conn is not None, "StateDb not connected"
        now = _now_iso()
        if increment_turn_count:
            await self._conn.execute(
                """
                UPDATE threads
                SET updated_at = ?,
                    preview = COALESCE(?, preview),
                    turn_count = turn_count + 1
                WHERE id = ?
                """,
                (now, preview, id),
            )
        else:
            await self._conn.execute(
                """
                UPDATE threads
                SET updated_at = ?,
                    preview = COALESCE(?, preview)
                WHERE id = ?
                """,
                (now, preview, id),
            )
        await self._conn.commit()

    async def get_thread(self, id: str) -> Optional[ThreadRecord]:
        """Fetch a single thread by its UUID."""
        assert self._conn is not None, "StateDb not connected"
        cursor = await self._conn.execute(
            "SELECT * FROM threads WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return ThreadRecord(**dict(row)) if row else None

    async def get_thread_by_name(self, name: str) -> Optional[ThreadRecord]:
        """Fetch a single thread by its human-readable name."""
        assert self._conn is not None, "StateDb not connected"
        cursor = await self._conn.execute(
            "SELECT * FROM threads WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        return ThreadRecord(**dict(row)) if row else None

    async def delete_thread(self, id: str) -> None:
        """Permanently delete a thread record."""
        assert self._conn is not None, "StateDb not connected"
        await self._conn.execute("DELETE FROM threads WHERE id = ?", (id,))
        await self._conn.commit()
