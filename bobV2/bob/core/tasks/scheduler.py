from __future__ import annotations

import asyncio
import time
from typing import Any


class CronScheduler:
    """
    Minimal scheduler loop that can enqueue due cron tasks.

    This is a bootstrap implementation. It uses task payload fields:
    - "cron_interval_seconds"
    - "cron_next_run_at"
    """

    def __init__(self, runtime: Any, poll_interval: float = 2.0) -> None:
        self.runtime = runtime
        self.poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

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
            now = int(time.time())
            all_tasks = self.runtime.store.list_tasks(status=None, limit=2000)
            latest_by_key: dict[str, Any] = {}

            # Keep only the latest task for each cron key.
            for task in all_tasks:
                if task.type != "cron_triggered":
                    continue
                payload = task.payload or {}
                key = str(payload.get("cron_key") or task.id)
                current = latest_by_key.get(key)
                if current is None or task.created_at_ts > current.created_at_ts:
                    latest_by_key[key] = task

            for key, task in latest_by_key.items():
                payload = dict(task.payload or {})
                interval = int(payload.get("cron_interval_seconds", 0) or 0)
                next_run = int(payload.get("cron_next_run_at", 0) or 0)
                if interval <= 0 or next_run <= 0:
                    continue

                # If a run is already pending/active for this cron stream, do not enqueue.
                if task.status in {"queued", "running"}:
                    continue

                # Only schedule when this stream is due.
                if next_run > now:
                    continue

                next_payload = dict(payload)
                next_payload["cron_key"] = key
                next_payload["cron_next_run_at"] = now + interval

                try:
                    created = await self.runtime.create_task(
                        task_type="cron_triggered",
                        payload=next_payload,
                        priority=task.priority,
                        max_attempts=task.max_attempts,
                        timeout_seconds=task.timeout_seconds,
                        run_at_ts=now,
                    )
                    self.runtime.store.add_event(
                        task.id,
                        "task.cron_scheduled",
                        {
                            "cron_key": key,
                            "spawned_task_id": created.get("id"),
                            "scheduled_at_ts": now,
                            "next_run_at_ts": next_payload["cron_next_run_at"],
                        },
                    )
                except Exception:
                    # Scheduler errors must not stop the loop.
                    pass
            await asyncio.sleep(self.poll_interval)
