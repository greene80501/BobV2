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
                    title TEXT,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    session_id TEXT,
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
                    completed_at_ts INTEGER,
                    background INTEGER NOT NULL DEFAULT 0,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    group_id TEXT,
                    group_size INTEGER NOT NULL DEFAULT 0,
                    group_index INTEGER NOT NULL DEFAULT 0,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                )
                """
            )
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
            }
            for name, ddl in (
                ("title", "ALTER TABLE agent_runs ADD COLUMN title TEXT"),
                ("session_id", "ALTER TABLE agent_runs ADD COLUMN session_id TEXT"),
                ("completed_at_ts", "ALTER TABLE agent_runs ADD COLUMN completed_at_ts INTEGER"),
                ("background", "ALTER TABLE agent_runs ADD COLUMN background INTEGER NOT NULL DEFAULT 0"),
                ("run_count", "ALTER TABLE agent_runs ADD COLUMN run_count INTEGER NOT NULL DEFAULT 0"),
                ("group_id", "ALTER TABLE agent_runs ADD COLUMN group_id TEXT"),
                ("group_size", "ALTER TABLE agent_runs ADD COLUMN group_size INTEGER NOT NULL DEFAULT 0"),
                ("group_index", "ALTER TABLE agent_runs ADD COLUMN group_index INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in existing:
                    conn.execute(ddl)

    def upsert_record(self, thread_id: str, record: Any) -> None:
        now = _now_ms()
        created_at = int((getattr(record, "started_at", 0.0) or 0.0) * 1000) or now
        started_at_ts = int((getattr(record, "started_at", 0.0) or 0.0) * 1000) or None
        completed_at_ts = int((getattr(record, "completed_at", 0.0) or 0.0) * 1000) or None
        merge_success = getattr(record, "merge_success", None)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    agent_id, thread_id, path, name, agent_type, title, task, status, session_id,
                    cwd, worktree_path, definition_source, isolation_mode, permission_mode,
                    result, error, merge_status, merge_success, tool_uses, tokens,
                    last_activity, started_at_ts, completed_at_ts, background, run_count,
                    group_id, group_size, group_index, created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    title=excluded.title,
                    status=excluded.status,
                    session_id=excluded.session_id,
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
                    completed_at_ts=excluded.completed_at_ts,
                    background=excluded.background,
                    run_count=excluded.run_count,
                    group_id=excluded.group_id,
                    group_size=excluded.group_size,
                    group_index=excluded.group_index,
                    updated_at_ts=excluded.updated_at_ts
                """,
                (
                    record.agent_id,
                    thread_id,
                    str(record.path),
                    record.path.name,
                    getattr(record, "agent_type", "general"),
                    getattr(record, "title", None),
                    record.task,
                    record.status.value,
                    getattr(record, "session_id", None),
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
                    completed_at_ts,
                    1 if bool(getattr(record, "background", False)) else 0,
                    int(getattr(record, "run_count", 0) or 0),
                    getattr(record, "group_id", None),
                    int(getattr(record, "group_size", 0) or 0),
                    int(getattr(record, "group_index", 0) or 0),
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
            "title": row["title"],
            "task": row["task"],
            "status": row["status"],
            "session_id": row["session_id"],
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
            "completed_at_ts": row["completed_at_ts"],
            "background": bool(row["background"]),
            "run_count": row["run_count"],
            "group_id": row["group_id"],
            "group_size": row["group_size"],
            "group_index": row["group_index"],
        }
