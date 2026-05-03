from __future__ import annotations

from pathlib import Path

from bob.core.agents.registry import AgentPath, AgentRecord
from bob.core.agents.store import AgentRunStore


def test_agent_store_round_trip(tmp_path: Path) -> None:
    store = AgentRunStore(tmp_path / "agent_runs.sqlite")
    record = AgentRecord(
        agent_id="abc12345",
        path=AgentPath.parse("/root/worker"),
        task="Review the auth changes",
        agent_type="worker",
    )
    record.cwd = str(tmp_path)
    record.isolation_mode = "shared_workspace"
    record.permission_mode = "read_only"
    record.progress.tool_use_count = 3
    record.progress.token_count = 120
    record.progress.last_activity = "grep_files: auth"

    store.upsert_record("thread-1", record)

    fetched = store.get("thread-1", "abc12345")

    assert fetched is not None
    assert fetched["agent_id"] == "abc12345"
    assert fetched["agent_type"] == "worker"
    assert fetched["tool_uses"] == 3
    assert fetched["tokens"] == 120
    assert fetched["last_activity"] == "grep_files: auth"
