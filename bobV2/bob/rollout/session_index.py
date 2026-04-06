from __future__ import annotations

from pathlib import Path
from typing import Optional

from bob.rollout.state_db import StateDb, ThreadRecord


class SessionIndex:
    """
    High-level interface for session listing and lookup.

    Wraps :class:`StateDb` to provide a clean API used by the CLI and TUI
    without exposing raw SQL calls.
    """

    def __init__(self, state_db: StateDb) -> None:
        self._db = state_db

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    async def list_sessions(
        self,
        page: int = 0,
        page_size: int = 25,
        cwd_filter: Optional[str] = None,
    ) -> list[ThreadRecord]:
        """
        Return a page of sessions ordered by creation time (newest first).

        Parameters
        ----------
        page:
            Zero-based page number.
        page_size:
            Number of sessions per page.
        cwd_filter:
            When provided, only sessions whose ``cwd`` exactly matches this
            value are returned.  Pass ``str(Path.cwd())`` to restrict results
            to the current project.
        """
        return await self._db.list_threads(
            limit=page_size,
            offset=page * page_size,
            cwd_filter=cwd_filter,
        )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def find_by_name(self, name: str) -> Optional[ThreadRecord]:
        """Find a session by its human-readable name."""
        return await self._db.get_thread_by_name(name)

    async def find_by_id(self, id: str) -> Optional[ThreadRecord]:
        """Find a session by its UUID."""
        return await self._db.get_thread(id)

    async def find(self, name_or_id: str) -> Optional[ThreadRecord]:
        """
        Find a session by either name or UUID.

        Tries name first; falls back to UUID lookup.
        """
        record = await self.find_by_name(name_or_id)
        if record is None:
            record = await self.find_by_id(name_or_id)
        return record
