from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _ts() -> int:
    return int(time.time())


@dataclass
class TaskRecord:
    id: str
    type: str
    status: str
    priority: str
    payload: dict[str, Any]
    created_at_ts: int
    updated_at_ts: int
    max_attempts: int
    timeout_seconds: int
    run_at_ts: int
    result: Optional[dict[str, Any]] = None


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    max_attempts INTEGER NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    run_at_ts INTEGER NOT NULL,
                    created_at_ts INTEGER NOT NULL,
                    updated_at_ts INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_runat ON tasks(status, run_at_ts);

                CREATE TABLE IF NOT EXISTS task_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at_ts INTEGER NOT NULL,
                    finished_at_ts INTEGER,
                    worker_id TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS task_attempts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at_ts INTEGER NOT NULL,
                    finished_at_ts INTEGER,
                    error TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS task_artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    metadata TEXT,
                    created_at_ts INTEGER NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS task_leases (
                    task_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    lease_until_ts INTEGER NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def create_task(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        priority: str,
        max_attempts: int,
        timeout_seconds: int,
        run_at_ts: Optional[int],
    ) -> TaskRecord:
        now = _ts()
        task_id = str(uuid.uuid4())
        run_at = int(run_at_ts or now)
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO tasks(id, type, status, priority, payload, max_attempts, timeout_seconds, run_at_ts, created_at_ts, updated_at_ts)
                VALUES(?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task_type,
                    priority,
                    json.dumps(payload, ensure_ascii=True),
                    int(max_attempts),
                    int(timeout_seconds),
                    run_at,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_task(task_id)  # type: ignore[return-value]

    def list_tasks(self, status: Optional[str], limit: int) -> list[TaskRecord]:
        conn = self._conn()
        try:
            if status:
                cur = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at_ts DESC LIMIT ?",
                    (status, max(1, min(limit, 1000))),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at_ts DESC LIMIT ?",
                    (max(1, min(limit, 1000)),),
                )
            rows = cur.fetchall()
            return [self._to_record(r) for r in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        conn = self._conn()
        try:
            cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cur.fetchone()
            return self._to_record(row) if row else None
        finally:
            conn.close()

    def cancel_task(self, task_id: str) -> bool:
        now = _ts()
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE tasks SET status='cancelled', updated_at_ts=? WHERE id=? AND status IN ('queued','running')",
                (now, task_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def claim_next(self, worker_id: str, lease_seconds: int = 30) -> Optional[TaskRecord]:
        now = _ts()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status='queued' AND run_at_ts <= ?
                ORDER BY
                    CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    created_at_ts ASC
                LIMIT 1
                """,
                (now,),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            task_id = str(row["id"])
            conn.execute(
                "UPDATE tasks SET status='running', updated_at_ts=? WHERE id=?",
                (now, task_id),
            )
            conn.execute(
                """
                INSERT INTO task_leases(task_id, worker_id, lease_until_ts)
                VALUES(?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET worker_id=excluded.worker_id, lease_until_ts=excluded.lease_until_ts
                """,
                (task_id, worker_id, now + int(lease_seconds)),
            )
            run_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO task_runs(id, task_id, status, started_at_ts, worker_id) VALUES(?, ?, 'running', ?, ?)",
                (run_id, task_id, now, worker_id),
            )
            conn.execute(
                "INSERT INTO task_attempts(id, task_id, attempt_number, status, started_at_ts) VALUES(?, ?, ?, 'running', ?)",
                (str(uuid.uuid4()), task_id, self._attempt_count(conn, task_id) + 1, now),
            )
            conn.commit()
            return self._to_record(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete_task(self, task_id: str, result: dict[str, Any]) -> None:
        now = _ts()
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE tasks SET status='completed', result=?, updated_at_ts=? WHERE id=?",
                (json.dumps(result, ensure_ascii=True), now, task_id),
            )
            conn.execute(
                "UPDATE task_runs SET status='completed', finished_at_ts=? WHERE task_id=? AND status='running'",
                (now, task_id),
            )
            conn.execute(
                "UPDATE task_attempts SET status='completed', finished_at_ts=? WHERE task_id=? AND status='running'",
                (now, task_id),
            )
            conn.execute("DELETE FROM task_leases WHERE task_id=?", (task_id,))
            conn.commit()
        finally:
            conn.close()

    def fail_task(self, task_id: str, error: str, retry_delay_seconds: int = 5) -> None:
        now = _ts()
        conn = self._conn()
        try:
            task = self.get_task(task_id)
            if task is None:
                return
            attempts = self._attempt_count(conn, task_id)
            terminal = attempts >= task.max_attempts
            if terminal:
                status = "failed"
                next_run = task.run_at_ts
            else:
                status = "queued"
                next_run = now + max(1, retry_delay_seconds)
            conn.execute(
                "UPDATE tasks SET status=?, updated_at_ts=?, run_at_ts=? WHERE id=?",
                (status, now, next_run, task_id),
            )
            conn.execute(
                "UPDATE task_runs SET status=?, finished_at_ts=? WHERE task_id=? AND status='running'",
                ("failed" if terminal else "retrying", now, task_id),
            )
            conn.execute(
                "UPDATE task_attempts SET status='failed', finished_at_ts=?, error=? WHERE task_id=? AND status='running'",
                (now, error[:2000], task_id),
            )
            conn.execute("DELETE FROM task_leases WHERE task_id=?", (task_id,))
            conn.commit()
        finally:
            conn.close()

    def add_event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO task_events(task_id, ts, event_type, payload) VALUES(?, ?, ?, ?)",
                (task_id, _ts(), event_type, json.dumps(payload, ensure_ascii=True, default=str)),
            )
            conn.commit()
        finally:
            conn.close()

    def list_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY id ASC LIMIT ?",
                (task_id, max(1, min(limit, 2000))),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "task_id": r["task_id"],
                    "ts": int(r["ts"]),
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload"]) if r["payload"] else {},
                }
                for r in rows
            ]
        finally:
            conn.close()

    def _attempt_count(self, conn: sqlite3.Connection, task_id: str) -> int:
        cur = conn.execute("SELECT COUNT(*) AS c FROM task_attempts WHERE task_id=?", (task_id,))
        row = cur.fetchone()
        return int(row["c"]) if row else 0

    def _to_record(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=str(row["id"]),
            type=str(row["type"]),
            status=str(row["status"]),
            priority=str(row["priority"]),
            payload=json.loads(row["payload"]) if row["payload"] else {},
            result=json.loads(row["result"]) if row["result"] else None,
            created_at_ts=int(row["created_at_ts"]),
            updated_at_ts=int(row["updated_at_ts"]),
            max_attempts=int(row["max_attempts"]),
            timeout_seconds=int(row["timeout_seconds"]),
            run_at_ts=int(row["run_at_ts"]),
        )

