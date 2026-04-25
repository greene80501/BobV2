from __future__ import annotations

from unittest.mock import ANY

import pytest

import bob.core.agents as agents_module
import bob.core.agents.manager as manager_module
from bob.core.agents.supervisor import AgentSupervisor, WorkflowNode
from bob.tools.multi_agent.run_workflow import run_workflow_handler


class _DummyToolRegistry:
    def __init__(self, tools: list[str]) -> None:
        self._tools = list(tools)

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def get_tool_capabilities(self, name: str):
        is_mutating = name in {"write_file", "apply_patch"}
        return type("Caps", (), {"is_mutating": is_mutating})()


class _DummySession:
    def __init__(self, tools: list[str]) -> None:
        self.tool_registry = _DummyToolRegistry(tools)


class _DummyContext:
    def __init__(self, tools: list[str]) -> None:
        self._session = _DummySession(tools)


class _RecordingManager:
    def __init__(self) -> None:
        self.spawn_calls: list[dict] = []
        self.wait_calls: list[dict] = []
        self.close_calls: list[dict] = []

    async def spawn(self, **kwargs) -> str:
        self.spawn_calls.append(kwargs)
        return "agent-1"

    async def wait(self, **kwargs) -> str | None:
        self.wait_calls.append(kwargs)
        return "done"

    async def close(self, **kwargs) -> None:
        self.close_calls.append(kwargs)


@pytest.mark.asyncio
async def test_run_workflow_blocks_missing_required_tools() -> None:
    out = await run_workflow_handler(
        {
            "nodes": [
                {
                    "id": "research",
                    "role": "default",
                    "task": "Search the web for current docs",
                    "required_tools": ["web_search"],
                    "read_only": True,
                }
            ],
            "require_real_agents": True,
        },
        _DummyContext(["read_file", "grep_files"]),
    )

    assert "Workflow blocked" in out
    assert "requires unavailable tools: web_search" in out


@pytest.mark.asyncio
async def test_run_workflow_blocks_read_only_mutating_allowlist() -> None:
    out = await run_workflow_handler(
        {
            "nodes": [
                {
                    "id": "review",
                    "role": "reviewer",
                    "task": "Review the plan only",
                    "read_only": True,
                    "allowed_tools": ["read_file", "apply_patch"],
                }
            ]
        },
        _DummyContext(["read_file", "apply_patch"]),
    )

    assert "Workflow blocked" in out
    assert "read-only but allows mutating tools: apply_patch" in out


@pytest.mark.asyncio
async def test_run_workflow_blocks_invalid_timeout() -> None:
    out = await run_workflow_handler(
        {
            "nodes": [
                {
                    "id": "research",
                    "role": "default",
                    "task": "Search the web for current docs",
                    "required_tools": ["web_search"],
                    "read_only": True,
                    "timeout_seconds": "slow",
                }
            ]
        },
        _DummyContext(["web_search", "read_file"]),
    )

    assert "Workflow blocked" in out
    assert "invalid timeout_seconds" in out


@pytest.mark.asyncio
async def test_run_workflow_blocks_real_agents_requirement_for_single_node() -> None:
    out = await run_workflow_handler(
        {
            "nodes": [
                {
                    "id": "research",
                    "role": "default",
                    "task": "Inspect the codebase only",
                    "read_only": True,
                }
            ],
            "require_real_agents": True,
        },
        _DummyContext(["read_file"]),
    )

    assert "Workflow blocked" in out
    assert "fewer than 2 nodes" in out


@pytest.mark.asyncio
async def test_run_workflow_allows_read_only_research_node_when_tools_available(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeManager:
        def __init__(self) -> None:
            captured["manager_created"] = True

    class _FakeSupervisor:
        def __init__(self, manager) -> None:
            captured["manager"] = manager

        async def run_workflow(self, *, session, nodes, mode):
            captured["session"] = session
            captured["nodes"] = nodes
            captured["mode"] = mode
            return {
                "nodes": [
                    {
                        "id": nodes[0].id,
                        "role": nodes[0].role,
                        "status": "completed",
                        "agent_id": "agent-1",
                        "result": "Found current docs",
                        "error": None,
                    }
                ]
            }

    monkeypatch.setattr(manager_module, "AgentManager", _FakeManager)
    monkeypatch.setattr(agents_module, "AgentSupervisor", _FakeSupervisor)

    out = await run_workflow_handler(
        {
            "nodes": [
                {
                    "id": "internet-research",
                    "role": "default",
                    "task": "Research current provider integration guidance",
                    "required_tools": ["web_search"],
                    "allowed_tools": ["web_search", "read_file"],
                    "read_only": True,
                    "timeout_seconds": 45,
                }
            ]
        },
        _DummyContext(["web_search", "read_file"]),
    )

    nodes = captured["nodes"]
    assert out.startswith("Workflow completed")
    assert captured["mode"] == "default"
    assert len(nodes) == 1
    node = nodes[0]
    assert node.id == "internet-research"
    assert node.required_tools == ["web_search"]
    assert node.allowed_tools == ["web_search", "read_file"]
    assert node.read_only is True
    assert node.timeout_seconds == 45.0


def test_run_workflow_import_smoke() -> None:
    from bob.tools.multi_agent.run_workflow import run_workflow_handler as imported
    from bob.core.agents.manager import AgentManager

    assert imported is not None
    assert AgentManager is not None


class _ClosingManager:
    def __init__(self) -> None:
        self.closed: list[tuple[str, str | None]] = []

    async def spawn(self, **_kwargs) -> str:
        return "agent-1"

    async def wait(self, **_kwargs) -> str | None:
        return "done"

    async def close(self, *, agent_id: str, reason: str | None, **_kwargs) -> None:
        self.closed.append((agent_id, reason))


@pytest.mark.asyncio
async def test_supervisor_closes_agent_after_node_completion() -> None:
    manager = _ClosingManager()
    supervisor = AgentSupervisor(manager)

    result = await supervisor.run_workflow(
        session=object(),
        nodes=[WorkflowNode(id="n1", role="default", task="inspect only")],
    )

    assert result["nodes"][0]["status"] == "completed"
    assert manager.closed == [("agent-1", "workflow_node_complete:n1")]


@pytest.mark.asyncio
async def test_supervisor_passes_read_only_research_policy_to_agent_manager() -> None:
    manager = _RecordingManager()
    supervisor = AgentSupervisor(manager)

    await supervisor.run_workflow(
        session=object(),
        nodes=[
            WorkflowNode(
                id="research",
                role="default",
                task="Inspect the codebase and search docs",
                allowed_tools=["web_search", "read_file"],
                read_only=True,
                timeout_seconds=30,
            )
        ],
    )

    assert manager.spawn_calls == [
        {
            "session": ANY,
            "task": "Inspect the codebase and search docs",
            "mode": "default",
            "role": "default",
            "allowed_tools": ["web_search", "read_file"],
            "allow_mutating_tools": False,
            "task_name": "research",
        }
    ]
    assert manager.wait_calls == [
        {
            "session": ANY,
            "agent_id": "agent-1",
            "timeout_seconds": 30,
        }
    ]
    assert manager.close_calls == [
        {
            "session": ANY,
            "agent_id": "agent-1",
            "reason": "workflow_node_complete:research",
        }
    ]


@pytest.mark.asyncio
async def test_supervisor_marks_timeout_as_failed_for_research_node() -> None:
    class _TimeoutManager(_RecordingManager):
        async def wait(self, **kwargs) -> str | None:
            self.wait_calls.append(kwargs)
            return None

    manager = _TimeoutManager()
    supervisor = AgentSupervisor(manager)

    result = await supervisor.run_workflow(
        session=object(),
        nodes=[WorkflowNode(id="research", role="default", task="Research docs", read_only=True)],
    )

    node = result["nodes"][0]
    assert node["status"] == "failed"
    assert node["error"] == "Agent timed out or returned no result"


@pytest.mark.asyncio
async def test_supervisor_blocks_downstream_research_node_when_dependency_fails() -> None:
    class _FailingManager(_RecordingManager):
        async def wait(self, **kwargs) -> str | None:
            self.wait_calls.append(kwargs)
            return None

    manager = _FailingManager()
    supervisor = AgentSupervisor(manager)

    result = await supervisor.run_workflow(
        session=object(),
        nodes=[
            WorkflowNode(id="codebase", role="default", task="Inspect the codebase", read_only=True),
            WorkflowNode(id="internet", role="default", task="Search the web", deps=["codebase"], read_only=True),
        ],
    )

    statuses = {node["id"]: node for node in result["nodes"]}
    assert statuses["codebase"]["status"] == "failed"
    assert statuses["internet"]["status"] == "blocked"
    assert statuses["internet"]["error"] == "Blocked by failed dependency"
