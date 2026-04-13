from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bob.core.thread_manager import AgentRecord, ThreadManager


class _FakeSession:
    def __init__(self, bob_home: Path, cwd: Path, session_id: str = "parent-session") -> None:
        self.bob_home = bob_home
        self.cwd = cwd
        self.session_id = session_id

    async def _emit(self, _event) -> None:
        return None


def _mk_record(*, agent_id: str, path: str, parent_id: str | None = None, status: str = "idle") -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        task="task",
        color="",
        name=None,
        role=None,
        path=path,
        parent_id=parent_id,
        depth=1 if parent_id is None else 2,
        cwd=".",
        model=None,
        template=None,
        created_at_ts=1,
        updated_at_ts=1,
        status=status,
    )


@pytest.mark.asyncio
async def test_spawn_uses_unique_paths_after_persisted_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bob_home = tmp_path / ".bob"
    agent_tree_dir = bob_home / "agent_trees"
    agent_tree_dir.mkdir(parents=True)
    persisted_path = agent_tree_dir / "parent-session.json"

    persisted_payload = {
        "parent_session_id": "parent-session",
        "updated_at_ts": 1,
        "agents": [
            {
                "id": "p1",
                "status": "closed",
                "task": "root",
                "name": None,
                "role": None,
                "path": "a1",
                "parent_id": None,
                "depth": 1,
                "cwd": str(tmp_path),
                "model": None,
                "template": None,
                "created_at_ts": 1,
                "updated_at_ts": 1,
                "closed_at_ts": 1,
                "last_result": None,
                "current_task": None,
                "children": ["c1"],
            },
            {
                "id": "c1",
                "status": "closed",
                "task": "child",
                "name": None,
                "role": None,
                "path": "a1/a1",
                "parent_id": "p1",
                "depth": 2,
                "cwd": str(tmp_path),
                "model": None,
                "template": None,
                "created_at_ts": 2,
                "updated_at_ts": 2,
                "closed_at_ts": 2,
                "last_result": None,
                "current_task": None,
                "children": [],
            },
        ],
    }
    persisted_path.write_text(json.dumps(persisted_payload), encoding="utf-8")

    manager = ThreadManager(_FakeSession(bob_home=bob_home, cwd=tmp_path))

    async def _fake_create_runtime(_rec: AgentRecord) -> None:
        return None

    async def _fake_assign_task(agent_id: str, task: str, **_kwargs) -> dict:
        rec = manager._agents[agent_id]
        rec.task = task
        return rec.to_snapshot()

    monkeypatch.setattr(manager, "_create_runtime_session", _fake_create_runtime)
    monkeypatch.setattr(manager, "assign_task", _fake_assign_task)

    root_id = await manager.spawn(task="next root")
    child_id = await manager.spawn(task="next child", parent_agent_id="p1")

    assert manager._agents[root_id].path == "a2"
    assert manager._agents[child_id].path == "a1/a2"


@pytest.mark.asyncio
async def test_wait_for_agents_does_not_finish_while_work_is_queued(tmp_path: Path) -> None:
    manager = ThreadManager(_FakeSession(bob_home=tmp_path / ".bob", cwd=tmp_path))
    rec = _mk_record(agent_id="a1", path="a1", status="queued")
    rec.queue.put_nowait("queued task")
    manager._agents[rec.id] = rec

    timed = await manager.wait_for_agents([rec.id], timeout=0.05)
    assert timed["timed_out"] is True
    assert timed["matched_agent_id"] is None

    rec.queue.get_nowait()
    rec.queue.task_done()
    rec.status = "idle"
    manager._bump_state()

    done = await manager.wait_for_agents([rec.id], timeout=0.2)
    assert done["timed_out"] is False
    assert done["matched_agent_id"] == rec.id


@pytest.mark.asyncio
async def test_close_clears_queue_and_resume_reactivates_failed_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ThreadManager(_FakeSession(bob_home=tmp_path / ".bob", cwd=tmp_path))
    rec = _mk_record(agent_id="a1", path="a1", status="failed")
    rec.queue.put_nowait("stale")
    manager._agents[rec.id] = rec

    await manager.close_agent(rec.id)
    assert rec.status == "closed"
    assert rec.queue.qsize() == 0

    async def _fake_create_runtime(_rec: AgentRecord) -> None:
        _rec.session = object()

    monkeypatch.setattr(manager, "_create_runtime_session", _fake_create_runtime)

    snap = await manager.resume_agent(rec.id)
    assert snap["status"] == "idle"
    assert rec.status == "idle"
    assert rec.closed_at_ts is None
