from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from bob.core.tasks.models import TaskStore
from bob.core.tasks.scheduler import CronScheduler
from bob.core.tasks.worker import TaskWorker


@dataclass
class CommandRuntimeRecord:
    id: str
    task_id: str
    thread_id: str
    command: str
    created_at_ts: int


class TaskRuntime:
    def __init__(self, *, db_path: Path, event_bus: Any, registry: Any) -> None:
        self.store = TaskStore(db_path)
        self.event_bus = event_bus
        self.registry = registry
        self.worker = TaskWorker(self)
        self.scheduler = CronScheduler(self)
        self._commands: dict[str, CommandRuntimeRecord] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        await self.worker.start()
        await self.scheduler.start()

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        await self.worker.stop()
        await self.scheduler.stop()

    async def create_task(
        self,
        *,
        task_type: str,
        payload: dict[str, Any],
        priority: str,
        max_attempts: int,
        timeout_seconds: int,
        run_at_ts: Optional[int],
    ) -> dict[str, Any]:
        rec = self.store.create_task(
            task_type=task_type,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            run_at_ts=run_at_ts,
        )
        event = {"task_id": rec.id, "event": {"type": "task.created", "task_type": rec.type}}
        self.store.add_event(rec.id, "task.created", event["event"])
        await self.event_bus.publish([f"task:{rec.id}"], event)
        return self._task_to_dict(rec)

    async def list_tasks(self, status: Optional[str], limit: int) -> list[dict[str, Any]]:
        return [self._task_to_dict(x) for x in self.store.list_tasks(status=status, limit=limit)]

    async def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        rec = self.store.get_task(task_id)
        if rec is None:
            return None
        data = self._task_to_dict(rec)
        data["events"] = self.store.list_events(task_id, limit=500)
        return data

    async def cancel_task(self, task_id: str) -> bool:
        ok = self.store.cancel_task(task_id)
        if ok:
            await self.event_bus.publish(
                [f"task:{task_id}"],
                {"task_id": task_id, "event": {"type": "task.cancelled"}},
            )
        return ok

    async def start_command(self, *, thread_id: str, command: str, cwd: Optional[str]) -> dict[str, Any]:
        task = await self.create_task(
            task_type="local_shell",
            payload={"command": command, "cwd": cwd},
            priority="medium",
            max_attempts=1,
            timeout_seconds=900,
            run_at_ts=None,
        )
        command_id = str(uuid.uuid4())
        self._commands[command_id] = CommandRuntimeRecord(
            id=command_id,
            task_id=task["id"],
            thread_id=thread_id,
            command=command,
            created_at_ts=int(time.time() * 1000),
        )
        return {"command_id": command_id, "task_id": task["id"], "state": "running"}

    async def wait_command(self, *, thread_id: str, command_id: str, timeout_ms: int) -> dict[str, Any]:
        rec = self._commands.get(command_id)
        if rec is None or rec.thread_id != thread_id:
            return {"state": "not_found"}
        deadline = time.monotonic() + max(0.1, timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            task = self.store.get_task(rec.task_id)
            if task and task.status in {"completed", "failed", "cancelled"}:
                return {"state": task.status, "task_id": task.id, "result": task.result}
            await asyncio.sleep(0.1)
        return {"state": "running", "task_id": rec.task_id}

    async def terminate_command(self, *, thread_id: str, command_id: str) -> dict[str, Any]:
        rec = self._commands.get(command_id)
        if rec is None or rec.thread_id != thread_id:
            return {"state": "not_found"}
        ok = await self.cancel_task(rec.task_id)
        return {"state": "cancelled" if ok else "running", "task_id": rec.task_id}

    def _task_to_dict(self, rec) -> dict[str, Any]:
        return {
            "id": rec.id,
            "type": rec.type,
            "status": rec.status,
            "priority": rec.priority,
            "payload": rec.payload,
            "result": rec.result,
            "created_at_ts": rec.created_at_ts,
            "updated_at_ts": rec.updated_at_ts,
            "max_attempts": rec.max_attempts,
            "timeout_seconds": rec.timeout_seconds,
            "run_at_ts": rec.run_at_ts,
        }
