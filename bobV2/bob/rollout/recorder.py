from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
from typing import Optional

import aiofiles


class RolloutRecorder:
    """
    Writes structured events to a JSONL rollout file asynchronously.

    The recorder uses a background writer task and an asyncio.Queue so that
    callers can ``await recorder.write(record)`` without blocking on disk I/O.

    Lifecycle::

        recorder = RolloutRecorder(path, session_id, model, cwd)
        await recorder.start()
        await recorder.write({"type": "response_item", "item": {...}})
        await recorder.stop()   # flushes queue and closes file
    """

    def __init__(
        self,
        path: Path,
        session_id: str,
        model: str,
        cwd: str,
    ) -> None:
        self._path = path
        self._session_id = session_id
        self._model = model
        self._cwd = cwd
        self._queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._started = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Initialise the rollout file and start the background writer.

        Writes a ``session_meta`` record as the first line so the file is
        always identifiable even if the process is killed mid-session.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        meta: dict = {
            "type": "session_meta",
            "session_id": self._session_id,
            "model": self._model,
            "cwd": self._cwd,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        async with aiofiles.open(self._path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(meta) + "\n")

        self._task = asyncio.create_task(self._writer_loop())
        self._started = True

    async def start_append(self) -> None:
        """
        Start writer in append mode for an existing rollout file.

        If the file does not exist yet, this falls back to :meth:`start`
        so a valid ``session_meta`` header is written.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists() or self._path.stat().st_size == 0:
            await self.start()
            return
        self._task = asyncio.create_task(self._writer_loop())
        self._started = True

    async def write(self, record: dict) -> None:
        """
        Enqueue *record* for writing.

        Safe to call from any async context.  If the recorder has not been
        started, the record is silently dropped.
        """
        if self._started:
            await self._queue.put(record)

    async def stop(self) -> None:
        """
        Flush the queue and shut down the background writer.

        Sends the sentinel value ``None`` to the writer loop and awaits its
        completion, ensuring all buffered records are flushed before returning.
        """
        if self._task is not None:
            await self._queue.put(None)  # sentinel
            await self._task
            self._task = None
        self._started = False

    # ------------------------------------------------------------------
    # Internal writer loop
    # ------------------------------------------------------------------

    async def _writer_loop(self) -> None:
        """Background coroutine that drains the queue to disk."""
        async with aiofiles.open(self._path, "a", encoding="utf-8") as f:
            while True:
                record = await self._queue.get()
                if record is None:
                    # Sentinel received — flush and exit
                    await f.flush()
                    break
                try:
                    await f.write(json.dumps(record) + "\n")
                    await f.flush()
                except Exception:
                    # Never let a write error crash the background task.
                    pass


# ---------------------------------------------------------------------------
# Stand-alone loader
# ---------------------------------------------------------------------------


async def load_rollout(path: Path) -> list[dict]:
    """
    Load a JSONL rollout file and return all valid records.

    Truncated or malformed lines (e.g. from an abrupt process exit) are
    silently skipped so callers always receive a usable list.
    """
    records: list[dict] = []
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # skip truncated final line
    except FileNotFoundError:
        pass
    return records
