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
    status: str = "pending"
    agent_id: str | None = None
    result: str | None = None


class AgentSupervisor:
    """
    Lightweight team workflow primitive.

    Planner creates a task graph; supervisor executes ready nodes and marks
    completion for reviewer/verifier gates.
    """

    def __init__(self, manager) -> None:
        self._manager = manager

    async def _run_node(self, *, session, node: WorkflowNode, mode: str) -> str | None:
        node.agent_id = await self._manager.spawn(
            session=session,
            task=node.task,
            mode=mode if node.role in ("implementer", "reviewer", "verifier") else "default",
        )
        return await self._manager.wait(session=session, agent_id=node.agent_id, timeout_seconds=None)

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
                if any(node_map[d].status != "completed" for d in node.deps if d in node_map):
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
                    node.status = "completed" if node.result is not None else "failed"
                except Exception:
                    node.status = "failed"
                    node.result = None

        return {
            "nodes": [
                {
                    "id": n.id,
                    "role": n.role,
                    "status": n.status,
                    "agent_id": n.agent_id,
                    "result": n.result,
                }
                for n in nodes
            ]
        }
