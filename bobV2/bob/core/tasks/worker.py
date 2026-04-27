from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from bob.core.tasks.executors import LocalExecutor, SshExecutor
from bob.core.tasks.queue import TaskQueue


class TaskWorker:
    def __init__(self, runtime: Any, poll_interval: float = 0.5) -> None:
        self.runtime = runtime
        self.poll_interval = poll_interval
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self.queue = TaskQueue(runtime.store, self.worker_id)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.executors = {
            "local_shell": LocalExecutor(),
            "remote_shell": SshExecutor(),
            "cron_triggered": LocalExecutor(),
        }

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            rec = self.queue.claim_next()
            if rec is None:
                await asyncio.sleep(self.poll_interval)
                continue

            self.runtime.store.add_event(rec.id, "task.claimed", {"worker_id": self.worker_id, "type": rec.type})
            await self.runtime.event_bus.publish(
                [f"task:{rec.id}"],
                {"task_id": rec.id, "event": {"type": "task.claimed", "worker_id": self.worker_id}},
            )
            started = time.monotonic()

            ex = self.executors.get(rec.type)
            if ex is None:
                self.runtime.store.fail_task(rec.id, f"Unsupported task type: {rec.type}", retry_delay_seconds=1)
                self.runtime.store.add_event(rec.id, "task.failed", {"error": "unsupported task type"})
                continue
            try:
                result = await ex.execute(rec.payload, self.runtime)
                duration_ms = int((time.monotonic() - started) * 1000)
                if result.ok:
                    out = dict(result.result)
                    out["duration_ms"] = duration_ms
                    self.runtime.store.complete_task(rec.id, out)
                    self.runtime.store.add_event(rec.id, "task.completed", out)
                    await self.runtime.event_bus.publish(
                        [f"task:{rec.id}"],
                        {"task_id": rec.id, "event": {"type": "task.completed", "result": out}},
                    )
                else:
                    self.runtime.store.fail_task(rec.id, result.error or "task failed")
                    self.runtime.store.add_event(rec.id, "task.failed", {"error": result.error or "task failed"})
                    await self.runtime.event_bus.publish(
                        [f"task:{rec.id}"],
                        {"task_id": rec.id, "event": {"type": "task.failed", "error": result.error or "task failed"}},
                    )
            except Exception as exc:
                self.runtime.store.fail_task(rec.id, str(exc))
                self.runtime.store.add_event(rec.id, "task.failed", {"error": str(exc)})
                await self.runtime.event_bus.publish(
                    [f"task:{rec.id}"],
                    {"task_id": rec.id, "event": {"type": "task.failed", "error": str(exc)}},
                )
