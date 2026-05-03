"""Async SQLite analytics store for Bob.

Stores one row per model turn with tokens, cost, and latency.
Database lives at ~/.bob/analytics.db.

Schema is append-only — we never update or delete rows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id            TEXT    NOT NULL,
    turn_id               TEXT,
    model                 TEXT    NOT NULL,
    provider              TEXT,
    input_tokens          INTEGER DEFAULT 0,
    output_tokens         INTEGER DEFAULT 0,
    total_tokens          INTEGER DEFAULT 0,
    cached_input_tokens   INTEGER DEFAULT 0,
    input_cost_usd        REAL,
    output_cost_usd       REAL,
    total_cost_usd        REAL,
    latency_ms            INTEGER,
    changed_files         TEXT,
    timestamp             TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_turns_session   ON turns (session_id);
CREATE INDEX IF NOT EXISTS idx_turns_model     ON turns (model);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns (timestamp);
"""


class AnalyticsDB:
    """Async SQLite wrapper for turn analytics."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ready = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Create the database file and tables if they don't exist."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                await db.executescript(_SCHEMA)
                # Migrations for existing DBs
                for migration in [
                    "ALTER TABLE turns ADD COLUMN changed_files TEXT",
                    "ALTER TABLE turns ADD COLUMN cached_input_tokens INTEGER DEFAULT 0",
                ]:
                    try:
                        await db.execute(migration)
                        await db.commit()
                    except Exception:
                        pass  # Column already exists
            self._ready = True
        except Exception as exc:
            logger.warning("Analytics DB setup failed (continuing without analytics): %s", exc)
            self._ready = False

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def record_turn(
        self,
        *,
        session_id: str,
        turn_id: Optional[str] = None,
        model: str,
        provider: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        cached_input_tokens: int = 0,
        input_cost_usd: Optional[float] = None,
        output_cost_usd: Optional[float] = None,
        total_cost_usd: Optional[float] = None,
        latency_ms: Optional[int] = None,
        changed_files: Optional[list[str]] = None,
    ) -> None:
        """Insert one turn record. Silently skips if DB is unavailable."""
        if not self._ready:
            return
        import json
        changed_files_json = json.dumps(changed_files) if changed_files else None
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO turns
                        (session_id, turn_id, model, provider,
                         input_tokens, output_tokens, total_tokens,
                         cached_input_tokens,
                         input_cost_usd, output_cost_usd, total_cost_usd,
                         latency_ms, changed_files)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        session_id, turn_id, model, provider,
                        input_tokens, output_tokens, total_tokens,
                        cached_input_tokens,
                        input_cost_usd, output_cost_usd, total_cost_usd,
                        latency_ms, changed_files_json,
                    ),
                )
                await db.commit()
        except Exception as exc:
            logger.debug("Analytics record_turn failed: %s", exc)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def session_totals(self, session_id: str) -> dict[str, Any]:
        """Aggregate totals for one session."""
        if not self._ready:
            return _empty_totals()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                row = await (await db.execute(
                    """
                    SELECT
                        COUNT(*)            AS turns,
                        SUM(input_tokens)   AS input_tokens,
                        SUM(output_tokens)  AS output_tokens,
                        SUM(total_tokens)   AS total_tokens,
                        SUM(cached_input_tokens) AS cached_input_tokens,
                        SUM(total_cost_usd) AS total_cost_usd,
                        AVG(latency_ms)     AS avg_latency_ms
                    FROM turns
                    WHERE session_id = ?
                    """,
                    (session_id,),
                )).fetchone()
                return _row_to_totals(row)
        except Exception:
            return _empty_totals()

    async def all_time_totals(self) -> dict[str, Any]:
        """Aggregate totals across all sessions."""
        if not self._ready:
            return _empty_totals()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                row = await (await db.execute(
                    """
                    SELECT
                        COUNT(*)            AS turns,
                        SUM(input_tokens)   AS input_tokens,
                        SUM(output_tokens)  AS output_tokens,
                        SUM(total_tokens)   AS total_tokens,
                        SUM(cached_input_tokens) AS cached_input_tokens,
                        SUM(total_cost_usd) AS total_cost_usd,
                        AVG(latency_ms)     AS avg_latency_ms
                    FROM turns
                    """,
                )).fetchone()
                return _row_to_totals(row)
        except Exception:
            return _empty_totals()

    async def model_breakdown(self, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Cost and token totals grouped by model."""
        if not self._ready:
            return []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                if session_id:
                    rows = await (await db.execute(
                        """
                        SELECT model,
                               COUNT(*)            AS turns,
                               SUM(total_tokens)   AS total_tokens,
                               SUM(total_cost_usd) AS total_cost_usd
                        FROM turns WHERE session_id = ?
                        GROUP BY model ORDER BY total_cost_usd DESC
                        """,
                        (session_id,),
                    )).fetchall()
                else:
                    rows = await (await db.execute(
                        """
                        SELECT model,
                               COUNT(*)            AS turns,
                               SUM(total_tokens)   AS total_tokens,
                               SUM(total_cost_usd) AS total_cost_usd
                        FROM turns
                        GROUP BY model ORDER BY total_cost_usd DESC
                        """,
                    )).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def recent_turns(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent turn records."""
        if not self._ready:
            return []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                rows = await (await db.execute(
                    "SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,)
                )).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def turn_history(
        self,
        session_id: str,
        *,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return recent-to-oldest turn records for a specific session."""
        if not self._ready:
            return []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                if limit is None:
                    rows = await (await db.execute(
                        "SELECT * FROM turns WHERE session_id = ? ORDER BY id DESC",
                        (session_id,),
                    )).fetchall()
                else:
                    rows = await (await db.execute(
                        "SELECT * FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                        (session_id, limit),
                    )).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_totals() -> dict[str, Any]:
    return {
        "turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": None,
    }


def _row_to_totals(row: Any) -> dict[str, Any]:
    if not row:
        return _empty_totals()
    return {
        "turns":          int(row["turns"] or 0),
        "input_tokens":   int(row["input_tokens"] or 0),
        "output_tokens":  int(row["output_tokens"] or 0),
        "total_tokens":   int(row["total_tokens"] or 0),
        "cached_input_tokens": int(row["cached_input_tokens"] or 0),
        "total_cost_usd": float(row["total_cost_usd"] or 0.0),
        "avg_latency_ms": float(row["avg_latency_ms"]) if row["avg_latency_ms"] else None,
    }
