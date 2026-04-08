"""
Cron/Schedule tools for Bob.

Two tools exposed to the model:
- schedule_cron(cron_expr, task_description)  → schedule_id
- remote_trigger(schedule_id)                → runs the task immediately

Storage: ~/.bob/schedules.db  (SQLite)
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    p = Path.home() / ".bob" / "schedules.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id           TEXT    PRIMARY KEY,
            cron_expr    TEXT    NOT NULL,
            description  TEXT    NOT NULL,
            enabled      INTEGER NOT NULL DEFAULT 1,
            last_run_at  TEXT,
            next_run_at  TEXT,
            run_count    INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id  TEXT    NOT NULL,
            started_at   TEXT    NOT NULL,
            finished_at  TEXT,
            status       TEXT    NOT NULL DEFAULT 'running',
            output       TEXT
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Cron expression parser (next-run calculation)
# ---------------------------------------------------------------------------

def _next_run(cron_expr: str, after: datetime | None = None) -> datetime | None:
    """Very lightweight cron calculator (minute granularity, no seconds/years).

    Supports standard 5-field cron: minute hour dom month dow
    Fields may be: * (any), N (exact), */N (every N), N-M (range).
    Returns None if the expression is invalid.
    """
    try:
        from croniter import croniter  # type: ignore
        base = after or datetime.now(timezone.utc)
        ci = croniter(cron_expr, base)
        return ci.get_next(datetime)
    except ImportError:
        pass
    # Minimal fallback: just return None if croniter not available
    return None


# ---------------------------------------------------------------------------
# schedule_cron tool
# ---------------------------------------------------------------------------

SCHEDULE_CRON_DESCRIPTION = (
    "Create a recurring scheduled task. "
    "Specify a standard 5-field cron expression (minute hour dom month dow) "
    "and a natural-language description of what should run. "
    "Returns a schedule_id you can use with remote_trigger to fire it manually."
)

SCHEDULE_CRON_SCHEMA = {
    "type": "object",
    "properties": {
        "cron_expr": {
            "type": "string",
            "description": (
                "Standard cron expression with 5 fields: "
                "'minute hour day-of-month month day-of-week'. "
                "Examples: '0 9 * * 1-5' (weekdays 9am), '*/30 * * * *' (every 30 min)."
            ),
        },
        "task_description": {
            "type": "string",
            "description": "Natural-language description of what the schedule should do.",
        },
    },
    "required": ["cron_expr", "task_description"],
}


async def schedule_cron_handler(tool_input: dict, context: Any) -> str:
    cron_expr: str = tool_input.get("cron_expr", "").strip()
    description: str = tool_input.get("task_description", "").strip()

    if not cron_expr:
        return "Error: cron_expr is required"
    if not description:
        return "Error: task_description is required"

    # Validate cron expression has 5 fields
    fields = cron_expr.split()
    if len(fields) != 5:
        return f"Error: cron_expr must have exactly 5 fields (got {len(fields)}): '{cron_expr}'"

    schedule_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()
    next_run = _next_run(cron_expr)
    next_run_str = next_run.isoformat() if next_run else None

    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO schedules (id, cron_expr, description, next_run_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (schedule_id, cron_expr, description, next_run_str, now),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        return f"Error saving schedule: {exc}"

    lines = [
        f"✓ Schedule created (id={schedule_id})",
        f"  cron:  {cron_expr}",
        f"  task:  {description}",
    ]
    if next_run_str:
        lines.append(f"  next:  {next_run_str}")
    lines.append("Use remote_trigger(schedule_id) to fire it immediately.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# remote_trigger tool
# ---------------------------------------------------------------------------

REMOTE_TRIGGER_DESCRIPTION = (
    "Manually fire a scheduled task immediately, regardless of its cron schedule. "
    "Returns the schedule description so the model knows what to execute."
)

REMOTE_TRIGGER_SCHEMA = {
    "type": "object",
    "properties": {
        "schedule_id": {
            "type": "string",
            "description": "The schedule_id returned by schedule_cron.",
        },
    },
    "required": ["schedule_id"],
}


async def remote_trigger_handler(tool_input: dict, context: Any) -> str:
    schedule_id: str = tool_input.get("schedule_id", "").strip()
    if not schedule_id:
        return "Error: schedule_id is required"

    try:
        conn = _connect()
        row = conn.execute(
            "SELECT id, cron_expr, description, enabled, run_count FROM schedules WHERE id = ?",
            (schedule_id,),
        ).fetchone()
    except Exception as exc:
        return f"Error querying schedule: {exc}"

    if not row:
        return f"Error: no schedule found with id='{schedule_id}'"

    sid, cron_expr, description, enabled, run_count = row
    if not enabled:
        return f"Schedule '{schedule_id}' is disabled. Enable it first."

    # Record the run
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO schedule_runs (schedule_id, started_at, status) VALUES (?, ?, 'triggered')",
            (schedule_id, now),
        )
        conn.execute(
            "UPDATE schedules SET last_run_at=?, run_count=run_count+1 WHERE id=?",
            (now, schedule_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return (
        f"✓ Triggered schedule '{schedule_id}'\n"
        f"  task: {description}\n"
        f"  cron: {cron_expr}\n"
        f"  runs: {run_count + 1}\n"
        f"\nNow execute the task: {description}"
    )


# ---------------------------------------------------------------------------
# list_schedules (utility, not a tool — used by /tasks or /status)
# ---------------------------------------------------------------------------

def list_schedules() -> list[dict]:
    """Return all schedules as dicts. Used by TUI slash commands."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT id, cron_expr, description, enabled, last_run_at, next_run_at, run_count, created_at "
            "FROM schedules ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        cols = ["id", "cron_expr", "description", "enabled", "last_run_at", "next_run_at", "run_count", "created_at"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []
