from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SwarmAuditLog:
    """Per-run JSONL audit trail written to ~/.bob/swarm_runs/<run_id>/."""

    def __init__(self, run_id: str, bob_home: Path, task: str):
        self.run_id = run_id
        self.run_dir = bob_home / "swarm_runs" / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._audit_path = self.run_dir / "audit.jsonl"
        self._plan_path = self.run_dir / "plan.json"
        self._patch_path = self.run_dir / "changes.patch"
        self._start_ts = time.time()

        self._write({"event": "swarm_started", "run_id": run_id, "task": task})

    @property
    def audit_path(self) -> str:
        return str(self._audit_path)

    def _write(self, record: dict[str, Any]) -> None:
        record.setdefault("ts", time.time())
        try:
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def log_phase(self, phase: str) -> None:
        self._write({"event": "phase_started", "phase": phase})

    def log_agent_spawned(self, agent_id: str, role: str, task_preview: str, workspace: str) -> None:
        self._write({
            "event": "agent_spawned",
            "agent_id": agent_id,
            "role": role,
            "task_preview": task_preview[:200],
            "workspace": workspace,
        })

    def log_agent_completed(self, agent_id: str, role: str,
                             files_modified: list[str], result_preview: str) -> None:
        self._write({
            "event": "agent_completed",
            "agent_id": agent_id,
            "role": role,
            "files_modified": files_modified,
            "result_preview": (result_preview or "")[:400],
        })

    def log_agent_stalled(self, agent_id: str, role: str) -> None:
        self._write({"event": "agent_stalled", "agent_id": agent_id, "role": role})

    def log_plan_generated(self, plan_dict: dict) -> None:
        try:
            self._plan_path.write_text(
                json.dumps(plan_dict, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
        self._write({
            "event": "plan_generated",
            "tasks_count": len(plan_dict.get("tasks", [])),
            "affected_files": plan_dict.get("affected_files", []),
        })

    def log_authorization(self, approved: bool, feedback: str = "") -> None:
        self._write({"event": "authorization", "approved": approved, "feedback": feedback})

    def log_patch_ready(self, files_changed: list[str], patch_text: str) -> None:
        try:
            self._patch_path.write_text(patch_text, encoding="utf-8")
        except OSError:
            pass
        self._write({
            "event": "patch_ready",
            "files_changed": files_changed,
            "patch_lines": patch_text.count("\n"),
        })

    def log_completed(self, success: bool, message: str = "") -> None:
        elapsed = round(time.time() - self._start_ts, 1)
        self._write({
            "event": "swarm_completed",
            "success": success,
            "message": message[:300],
            "elapsed_seconds": elapsed,
        })
