from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


class AgentRunStore:
    """Persist agent runs so they can be listed and queried after completion."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    agent_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cwd TEXT,
                    worktree_path TEXT,
                    definition_source TEXT,
                    isolation_mode TEXT NOT NULL,
                    permission_mode TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    merge_status TEXT,
                    merge_success INTEGER,
                    tool_uses INTEGER NOT NULL DEFAULT 0,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    last_activity TEXT,
                    started_at_ts INTEGER,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                )
                """
            )

    def upsert_record(self, thread_id: str, record: Any) -> None:
        now = _now_ms()
        created_at = int((getattr(record, "started_at", 0.0) or 0.0) * 1000) or now
        started_at_ts = int((getattr(record, "started_at", 0.0) or 0.0) * 1000) or None
        merge_success = getattr(record, "merge_success", None)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    agent_id, thread_id, path, name, agent_type, task, status,
                    cwd, worktree_path, definition_source, isolation_mode, permission_mode,
                    result, error, merge_status, merge_success, tool_uses, tokens,
                    last_activity, started_at_ts, created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    status=excluded.status,
                    cwd=excluded.cwd,
                    worktree_path=excluded.worktree_path,
                    definition_source=excluded.definition_source,
                    isolation_mode=excluded.isolation_mode,
                    permission_mode=excluded.permission_mode,
                    result=excluded.result,
                    error=excluded.error,
                    merge_status=excluded.merge_status,
                    merge_success=excluded.merge_success,
                    tool_uses=excluded.tool_uses,
                    tokens=excluded.tokens,
                    last_activity=excluded.last_activity,
                    started_at_ts=COALESCE(excluded.started_at_ts, agent_runs.started_at_ts),
                    updated_at_ts=excluded.updated_at_ts
                """,
                (
                    record.agent_id,
                    thread_id,
                    str(record.path),
                    record.path.name,
                    getattr(record, "agent_type", "worker"),
                    record.task,
                    record.status.value,
                    getattr(record, "cwd", None),
                    getattr(record, "worktree_path", None),
                    getattr(record, "definition_source", None),
                    getattr(record, "isolation_mode", "shared_workspace"),
                    getattr(record, "permission_mode", "full_auto"),
                    getattr(record, "result", None),
                    getattr(record, "error", None),
                    getattr(record, "merge_status", None),
                    None if merge_success is None else (1 if merge_success else 0),
                    getattr(record.progress, "tool_use_count", 0),
                    getattr(record.progress, "token_count", 0),
                    getattr(record.progress, "last_activity", ""),
                    started_at_ts,
                    created_at,
                    now,
                ),
            )

    def get(self, thread_id: str, agent_id: str) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE thread_id = ? AND agent_id = ?",
                (thread_id, agent_id),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def find_by_name(self, thread_id: str, name: str) -> Optional[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_runs
                WHERE thread_id = ? AND (name = ? OR path = ?)
                ORDER BY updated_at_ts DESC
                LIMIT 1
                """,
                (thread_id, name, name),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE thread_id = ? ORDER BY created_at_ts DESC",
                (thread_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_id": row["agent_id"],
            "path": row["path"],
            "name": row["name"],
            "agent_type": row["agent_type"],
            "task": row["task"],
            "status": row["status"],
            "cwd": row["cwd"],
            "worktree_path": row["worktree_path"],
            "definition_source": row["definition_source"],
            "isolation_mode": row["isolation_mode"],
            "permission_mode": row["permission_mode"],
            "result": row["result"],
            "error": row["error"],
            "merge_status": row["merge_status"],
            "merge_success": None if row["merge_success"] is None else bool(row["merge_success"]),
            "tool_uses": row["tool_uses"],
            "tokens": row["tokens"],
            "last_activity": row["last_activity"] or "",
            "created_at_ts": row["created_at_ts"],
            "updated_at_ts": row["updated_at_ts"],
            "started_at_ts": row["started_at_ts"],
        }
