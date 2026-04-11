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
            for task in self.runtime.store.list_tasks(status="completed", limit=500):
                if task.type != "cron_triggered":
                    continue
                interval = int(task.payload.get("cron_interval_seconds", 0) or 0)
                next_run = int(task.payload.get("cron_next_run_at", 0) or 0)
                if interval <= 0 or next_run <= now:
                    continue
            await asyncio.sleep(self.poll_interval)

