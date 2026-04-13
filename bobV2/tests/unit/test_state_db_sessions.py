from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def test_state_db_tracks_preview_and_updated_sort(tmp_path: Path) -> None:
    pytest.importorskip("aiosqlite")
    from bob.rollout.state_db import StateDb

    async def _run() -> None:
        db = StateDb(tmp_path / "state.sqlite")
        await db.connect()
        try:
            await db.upsert_thread(
                id="a1111111",
                name="first",
                path=str(tmp_path / "a.jsonl"),
                model="gpt",
                cwd=str(tmp_path),
            )
            await db.upsert_thread(
                id="b2222222",
                name="second",
                path=str(tmp_path / "b.jsonl"),
                model="gpt",
                cwd=str(tmp_path),
            )
            await db.touch_thread_activity(
                "a1111111",
                preview="user asked about resume command",
                increment_turn_count=True,
            )
            rows = await db.list_threads(limit=10, sort_by="updated_at")
            assert rows[0].id == "a1111111"
            assert rows[0].turn_count == 1
            assert "resume" in (rows[0].preview or "")
        finally:
            await db.close()

    asyncio.run(_run())
