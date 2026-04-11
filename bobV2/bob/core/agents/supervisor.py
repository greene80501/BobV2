from __future__ import annotations

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

    async def run_workflow(self, *, session, nodes: list[WorkflowNode], mode: str = "default") -> dict[str, Any]:
        node_map = {n.id: n for n in nodes}
        progress = True
        while progress:
            progress = False
            for node in nodes:
                if node.status != "pending":
                    continue
                if any(node_map[d].status != "completed" for d in node.deps if d in node_map):
                    continue
                node.status = "running"
                node.agent_id = await self._manager.spawn(
                    session=session,
                    task=node.task,
                    mode=mode if node.role in ("implementer", "reviewer", "verifier") else "default",
                )
                node.result = await self._manager.wait(session=session, agent_id=node.agent_id, timeout_seconds=None)
                node.status = "completed" if node.result is not None else "failed"
                progress = True

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

