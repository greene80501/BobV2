from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession

from bob.core.agents.registry import AgentPath, AgentRegistry, AgentRecord, AgentStatus
from bob.core.agents.mailbox import InterAgentMessage
from bob.core.agents.sub_agent import BobSubAgent


class AgentControl:
    """
    Central orchestrator for the sub-agent system. Attached to the parent BobSession.

    - spawn()        — create + start a sub-agent
    - send_message() — deliver a message to a running agent
    - wait_for()     — block until agents finish
    - close()        — cancel an agent
    - list_agents()  — snapshot of all agent states
    """

    def __init__(self, parent: "BobSession") -> None:
        self._parent = parent
        max_agents = getattr(parent.config, "multi_agent_max_agents", 8)
        self._registry = AgentRegistry(max_agents=max_agents, max_depth=1)
        self._agents: dict[str, BobSubAgent] = {}   # agent_id → agent
        self._completion_queue: asyncio.Queue[str] = asyncio.Queue()
        self._root_path = AgentPath.root()

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    async def spawn(
        self,
        task: str,
        *,
        name: Optional[str] = None,
        model: Optional[str] = None,
        fork_mode: str = "none",
    ) -> AgentRecord:
        """
        Spawn a new sub-agent running in a background asyncio.Task.
        Returns the AgentRecord immediately; the agent runs concurrently.
        """
        child_name = name or f"agent_{len(self._agents) + 1}"
        path = self._root_path.join(child_name)

        record = await self._registry.reserve(path, task)

        child_session = self._make_child_session(model=model, fork_mode=fork_mode)

        agent = BobSubAgent(
            record=record,
            session=child_session,
            parent_session=self._parent,
            completion_queue=self._completion_queue,
        )
        self._agents[record.agent_id] = agent
        agent.start()
        return record

    def _make_child_session(
        self,
        *,
        model: Optional[str],
        fork_mode: str,
    ) -> "BobSession":
        from bob.core.session import BobSession
        from bob.protocol.config_types import AskForApproval

        parent = self._parent
        overrides: dict = {"ask_for_approval": AskForApproval.NEVER}
        if model:
            overrides["model"] = model
        child_config = parent.config.model_copy(update=overrides)

        child_session = BobSession(
            config=child_config,
            cwd=parent.cwd,
            ephemeral=True,
        )

        # Sub-agents auto-approve all network access — no TUI to ask
        from bob.core.network_policy import NetworkPolicy
        child_session._network_policy = NetworkPolicy(network_access=True)

        if fork_mode != "none":
            history = list(parent.context_manager.raw_items())
            if fork_mode.startswith("last_n:"):
                try:
                    n = int(fork_mode.split(":")[1])
                    history = history[-(n * 4):] if len(history) > n * 4 else history
                except (IndexError, ValueError):
                    pass
            child_session.context_manager.replace(history)

        return child_session

    async def send_message(
        self,
        target: str,
        content: str,
        *,
        trigger_turn: bool = True,
    ) -> bool:
        """Queue a message to a running agent. Returns False if not found."""
        agent = self._find_agent(target)
        if agent is None:
            return False
        agent.mailbox.send(InterAgentMessage(
            author="parent",
            content=content,
            trigger_turn=trigger_turn,
        ))
        return True

    async def wait_for(
        self,
        targets: list[str],
        timeout_ms: int = 300_000,
    ) -> dict[str, dict]:
        """Block until all targets reach a terminal state. Returns results by agent_id."""
        wait_tasks = []
        resolved: dict[str, AgentRecord] = {}

        for target in targets:
            rec = await self._resolve_record(target)
            if rec is None:
                continue
            resolved[target] = rec
            wait_tasks.append(self._registry.wait_for(rec.agent_id, timeout_ms=timeout_ms))

        if wait_tasks:
            await asyncio.gather(*wait_tasks, return_exceptions=True)

        results: dict[str, dict] = {}
        for target in targets:
            rec = resolved.get(target) or await self._resolve_record(target)
            if rec is None:
                results[target] = {"status": "not_found", "result": None, "error": "agent not found"}
            else:
                results[rec.agent_id] = {
                    "status": rec.status.value,
                    "result": rec.result,
                    "error": rec.error,
                    "tool_uses": rec.progress.tool_use_count,
                    "tokens": rec.progress.token_count,
                }
        return results

    async def close(self, target: str) -> Optional[str]:
        """Cancel a running agent. Returns its previous status or None if not found."""
        agent = self._find_agent(target)
        if agent is None:
            rec = await self._resolve_record(target)
            return rec.status.value if rec else None
        rec = self._registry._agents.get(agent.agent_id)
        prev = rec.status.value if rec else "unknown"
        agent.cancel()
        return prev

    async def list_agents(self) -> list[dict]:
        return [
            {
                "agent_id": r.agent_id,
                "path": str(r.path),
                "name": r.path.name,
                "task": r.task[:100],
                "status": r.status.value,
                "last_activity": r.progress.last_activity,
                "tool_uses": r.progress.tool_use_count,
                "tokens": r.progress.token_count,
                "result_preview": (r.result or "")[:200] if r.result else None,
                "error": r.error,
            }
            for r in await self._registry.list_all()
        ]

    async def get_status(self, target: str) -> Optional[dict]:
        rec = await self._resolve_record(target)
        if rec is None:
            return None
        return {
            "agent_id": rec.agent_id,
            "path": str(rec.path),
            "status": rec.status.value,
            "last_activity": rec.progress.last_activity,
            "recent_activities": rec.progress.recent_activities,
            "tool_uses": rec.progress.tool_use_count,
            "tokens": rec.progress.token_count,
            "result": rec.result,
            "error": rec.error,
        }

    def count_active(self) -> int:
        return sum(
            1 for r in self._registry._agents.values()
            if not r.status.is_terminal
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_agent(self, target: str) -> Optional[BobSubAgent]:
        if target in self._agents:
            return self._agents[target]
        for agent in self._agents.values():
            if agent.path.name == target or str(agent.path) == target:
                return agent
        return None

    async def _resolve_record(self, target: str) -> Optional[AgentRecord]:
        rec = await self._registry.get(target)
        if rec:
            return rec
        return await self._registry.find_by_name(target)
