from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Callable, Awaitable, Optional


class SkillsWatcher:
    """Watches skill directories for file-system changes and fires a callback.

    Uses the ``watchfiles`` library when available; silently does nothing when
    it is not installed (rather than raising an ImportError at construction
    time).
    """

    def __init__(
        self,
        paths: list[Path],
        on_change: Callable[[], Awaitable[None]],
        debounce_ms: int = 300,
    ):
        """
        Parameters
        ----------
        paths:
            Directories to watch. Non-existent paths are silently skipped.
        on_change:
            Async callback invoked whenever a change is detected. Called
            at most once per *debounce_ms* milliseconds.
        debounce_ms:
            Minimum milliseconds between successive ``on_change`` calls.
        """
        self._paths = [p for p in paths if p.exists()]
        self._on_change = on_change
        self._debounce_s = debounce_ms / 1000.0
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start watching in a background asyncio task."""
        if not self._paths:
            return  # nothing to watch
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Cancel the background watcher task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    # ------------------------------------------------------------------
    # Internal watch loop
    # ------------------------------------------------------------------

    async def _watch_loop(self) -> None:
        try:
            from watchfiles import awatch  # type: ignore[import]
        except ImportError:
            # watchfiles not installed — watcher is a no-op
            return

        str_paths = [str(p) for p in self._paths]
        last_fire: float = 0.0
        import time

        try:
            async for _changes in awatch(*str_paths):
                now = time.monotonic()
                if now - last_fire >= self._debounce_s:
                    last_fire = now
                    try:
                        await self._on_change()
                    except Exception:
                        pass  # never let a callback crash the watcher
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
