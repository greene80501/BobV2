from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowNode:
    id: str
    role: str
    task: str
    deps: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None
    read_only: bool = False
    timeout_seconds: float | None = None
    status: str = "pending"
    agent_id: str | None = None
    result: str | None = None
    error: str | None = None


class AgentSupervisor:
    """
    Lightweight team workflow primitive.

    Planner creates a task graph; supervisor executes ready nodes and marks
    completion for reviewer/verifier gates.
    """

    def __init__(self, manager) -> None:
        self._manager = manager

    async def _run_node(self, *, session, node: WorkflowNode, mode: str) -> str | None:
        resolved_mode = mode if node.role in ("implementer", "reviewer", "verifier") else "default"
        allow_mutating_tools = None if not node.read_only else False
        node.agent_id = await self._manager.spawn(
            session=session,
            task=node.task,
            mode=resolved_mode,
            role=node.role,
            allowed_tools=node.allowed_tools,
            allow_mutating_tools=allow_mutating_tools,
            task_name=node.id,
        )
        try:
            return await self._manager.wait(
                session=session,
                agent_id=node.agent_id,
                timeout_seconds=node.timeout_seconds,
            )
        finally:
            if node.agent_id:
                await self._manager.close(
                    session=session,
                    agent_id=node.agent_id,
                    reason=f"workflow_node_complete:{node.id}",
                )

    async def run_workflow(self, *, session, nodes: list[WorkflowNode], mode: str = "default") -> dict[str, Any]:
        node_map = {n.id: n for n in nodes}
        pending: set[str] = {n.id for n in nodes}
        running: dict[asyncio.Task, str] = {}

        while pending or running:
            launched = False
            for node_id in list(pending):
                node = node_map[node_id]
                if node.status != "pending":
                    pending.discard(node_id)
                    continue
                missing_deps = [dep for dep in node.deps if dep not in node_map]
                if missing_deps:
                    node.status = "failed"
                    node.error = f"Missing dependencies: {', '.join(sorted(missing_deps))}"
                    pending.discard(node_id)
                    continue
                if any(node_map[d].status != "completed" for d in node.deps):
                    if any(node_map[d].status == "failed" for d in node.deps):
                        node.status = "blocked"
                        node.error = "Blocked by failed dependency"
                        pending.discard(node_id)
                    continue
                node.status = "running"
                t = asyncio.create_task(self._run_node(session=session, node=node, mode=mode))
                running[t] = node_id
                pending.discard(node_id)
                launched = True

            if not running:
                if pending and not launched:
                    for node_id in pending:
                        node_map[node_id].status = "failed"
                    break
                continue

            done, _ = await asyncio.wait(set(running.keys()), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                node_id = running.pop(task)
                node = node_map[node_id]
                try:
                    node.result = task.result()
                    if node.result is None:
                        node.status = "failed"
                        node.error = "Agent timed out or returned no result"
                    else:
                        node.status = "completed"
                        node.error = None
                except Exception as exc:
                    node.status = "failed"
                    node.result = None
                    node.error = str(exc)

        return {
            "nodes": [
                {
                    "id": n.id,
                    "role": n.role,
                    "status": n.status,
                    "agent_id": n.agent_id,
                    "result": n.result,
                    "error": n.error,
                }
                for n in nodes
            ]
        }
