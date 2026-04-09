"""
Agent memory snapshot storage.

Snapshots capture what a named sub-agent learned (key findings, files touched)
so future spawns of the same agent can pick up where the last run left off.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _db_path() -> Path:
    p = Path.home() / ".bob" / "agent_memory.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            agent_name TEXT    NOT NULL,
            task       TEXT    NOT NULL,
            snapshot   TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
    """)
    try:
        conn.execute("ALTER TABLE snapshots ADD COLUMN session_id TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_name ON snapshots(agent_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_session ON snapshots(agent_name, session_id)"
    )
    conn.commit()
    return conn


def save_snapshot(session_id: str, agent_name: str, task: str, snapshot: str) -> None:
    """Persist a memory snapshot for a named agent within a parent session."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO snapshots (session_id, agent_name, task, snapshot, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, agent_name, task[:500], snapshot, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        # Keep only the 10 most recent snapshots per agent/session to avoid unbounded growth
        conn.execute("""
            DELETE FROM snapshots
            WHERE agent_name = ? AND COALESCE(session_id, '') = COALESCE(?, '')
              AND id NOT IN (
                  SELECT id FROM snapshots
                  WHERE agent_name = ? AND COALESCE(session_id, '') = COALESCE(?, '')
                  ORDER BY id DESC LIMIT 10
              )
        """, (agent_name, session_id, agent_name, session_id))
        conn.commit()
    finally:
        conn.close()


def load_snapshot(session_id: str, agent_name: str) -> Optional[str]:
    """Return the most recent snapshot for *agent_name* in *session_id*, or None."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT snapshot, task, created_at FROM snapshots "
            "WHERE agent_name = ? AND COALESCE(session_id, '') = COALESCE(?, '') "
            "ORDER BY id DESC LIMIT 1",
            (agent_name, session_id),
        ).fetchone()
        if not row:
            # Best-effort fallback for older global snapshots created before session scoping.
            row = conn.execute(
                "SELECT snapshot, task, created_at FROM snapshots "
                "WHERE agent_name = ? ORDER BY id DESC LIMIT 1",
                (agent_name,),
            ).fetchone()
        if row:
            snapshot_text, task_text, created_at = row
            return (
                f"[Prior session — {created_at[:10]}]\n"
                f"Task: {task_text}\n\n"
                f"{snapshot_text}"
            )
        return None
    finally:
        conn.close()
