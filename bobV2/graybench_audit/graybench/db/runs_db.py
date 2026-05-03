"""CRUD operations for benchmark runs and tasks."""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from .engine import get_connection

log = logging.getLogger(__name__)


def new_run_id() -> str:
    """Generate a short unique run ID."""
    return uuid.uuid4().hex[:12]


def create_run(benchmark: str, model_provider: str, model_id: str,
               route: str = "direct", config: dict = None,
               environment: dict = None) -> str:
    """Create a new benchmark run. Returns run_id."""
    run_id = new_run_id()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO benchmark_runs
                (run_id, benchmark, model_provider, model_id, route,
                 status, config_json, environment_json)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (run_id, benchmark, model_provider, model_id, route,
              json.dumps(config) if config else None,
              json.dumps(environment) if environment else None))
        conn.commit()
    finally:
        conn.close()
    return run_id


def start_run(run_id: str) -> None:
    """Mark a run as started."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE benchmark_runs
            SET status='running', started_at=datetime('now')
            WHERE run_id=?
        """, (run_id,))
        conn.commit()
    finally:
        conn.close()


def complete_run(run_id: str, total_tasks: int, passed_tasks: int,
                 failed_tasks: int, score: float, total_cost_usd: float,
                 total_tokens: int, total_duration_s: float) -> None:
    """Mark a run as completed with aggregate results."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE benchmark_runs
            SET status='completed', completed_at=datetime('now'),
                total_tasks=?, passed_tasks=?, failed_tasks=?,
                score=?, total_cost_usd=?, total_tokens=?,
                total_duration_s=?
            WHERE run_id=?
        """, (total_tasks, passed_tasks, failed_tasks, score,
              total_cost_usd, total_tokens, total_duration_s, run_id))
        conn.commit()
    finally:
        conn.close()


def fail_run(run_id: str, error: str) -> None:
    """Mark a run as failed."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE benchmark_runs
            SET status='failed', completed_at=datetime('now'), error=?
            WHERE run_id=?
        """, (error, run_id))
        conn.commit()
    finally:
        conn.close()


def cancel_run(run_id: str) -> None:
    """Mark a run as canceled."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE benchmark_runs
            SET status='canceled', completed_at=datetime('now')
            WHERE run_id=?
        """, (run_id,))
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: str) -> Optional[dict]:
    """Get a run by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_runs(benchmark: str = None, status: str = None,
              limit: int = 50, offset: int = 0) -> list[dict]:
    """List runs with optional filters."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM benchmark_runs WHERE 1=1"
        params = []
        if benchmark:
            sql += " AND benchmark=?"
            params.append(benchmark)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def record_task(run_id: str, task_id: str, task_name: str = None,
                passed: bool = None, score: float = None,
                generated_code: str = None, expected_output: str = None,
                actual_output: str = None, error: str = None,
                tokens_used: int = 0, cost_usd: float = 0.0,
                duration_s: float = 0.0, attempts: int = 1,
                metadata: dict = None,
                raw_llm_response: str = None,
                input_tokens: int = 0, output_tokens: int = 0,
                cached_tokens: int = 0, reasoning_tokens: int = 0,
                failure_category: str = None) -> None:
    """Record a task result."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO benchmark_tasks
                (run_id, task_id, task_name, status, started_at, completed_at,
                 passed, score, attempts, error, generated_code,
                 expected_output, actual_output, tokens_used, cost_usd,
                 duration_s, metadata_json,
                 raw_llm_response, input_tokens, output_tokens,
                 cached_tokens, reasoning_tokens, failure_category)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, task_id) DO UPDATE SET
                status='completed', completed_at=datetime('now'),
                passed=excluded.passed, score=excluded.score,
                attempts=excluded.attempts, error=excluded.error,
                generated_code=excluded.generated_code,
                actual_output=excluded.actual_output,
                tokens_used=excluded.tokens_used, cost_usd=excluded.cost_usd,
                duration_s=excluded.duration_s, metadata_json=excluded.metadata_json,
                raw_llm_response=excluded.raw_llm_response,
                input_tokens=excluded.input_tokens, output_tokens=excluded.output_tokens,
                cached_tokens=excluded.cached_tokens, reasoning_tokens=excluded.reasoning_tokens,
                failure_category=excluded.failure_category
        """, (run_id, task_id, task_name, "completed",
              int(passed) if passed is not None else None, score, attempts,
              error, generated_code, expected_output, actual_output,
              tokens_used, cost_usd, duration_s,
              json.dumps(metadata) if metadata else None,
              raw_llm_response, input_tokens, output_tokens,
              cached_tokens, reasoning_tokens, failure_category))
        conn.commit()
    finally:
        conn.close()


def get_tasks(run_id: str) -> list[dict]:
    """Get all tasks for a run."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM benchmark_tasks WHERE run_id=? ORDER BY task_id",
            (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def delete_run(run_id: str) -> bool:
    """Delete a run and its tasks. Returns True if found."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM benchmark_tasks WHERE run_id=?", (run_id,))
        cur = conn.execute("DELETE FROM benchmark_runs WHERE run_id=?", (run_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
