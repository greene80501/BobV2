from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.core.session import BobSession

from bob.core.agents.definitions import AgentDefinitionRegistry
from bob.core.agents.mailbox import InterAgentMessage
from bob.core.agents.registry import AgentPath, AgentRecord, AgentRegistry
from bob.core.agents.runtime import (
    AgentDefinition,
    AgentIsolationMode,
    AgentPermissionMode,
)
from bob.core.agents.store import AgentRunStore
from bob.core.agents.sub_agent import BobSubAgent
from bob.core.agents.worktree import WorktreeManager


class AgentControl:
    """
    Central orchestrator for Bob's background sub-agent system.

    Agents can be spawned from reusable agent definitions and optionally run in
    isolated git worktrees.
    """

    def __init__(self, parent: "BobSession") -> None:
        self._parent = parent
        max_agents = getattr(parent.config, "multi_agent_max_agents", 8)
        self._registry = AgentRegistry(max_agents=max_agents, max_depth=1)
        self._agents: dict[str, BobSubAgent] = {}
        self._completion_queue: asyncio.Queue[str] = asyncio.Queue()
        self._root_path = AgentPath.root()
        self._definitions = AgentDefinitionRegistry(parent.bob_home, parent.cwd)
        self._worktrees = WorktreeManager(parent.cwd)
        self._store = AgentRunStore(parent.bob_home / "agent_runs.sqlite")

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    async def spawn(
        self,
        task: str,
        *,
        name: Optional[str] = None,
        agent_type: Optional[str] = None,
        model: Optional[str] = None,
        fork_mode: str = "none",
        isolation_mode: Optional[str] = None,
        permission_mode: Optional[str] = None,
    ) -> AgentRecord:
        child_type = (agent_type or "worker").strip() or "worker"
        definition = self._resolve_definition(child_type)
        child_name = name or derive_agent_name(task, fallback=definition.name or "worker")
        path = self._root_path.join(child_name)
        record = await self._registry.reserve(path, task)
        record.agent_type = definition.name

        effective_fork_mode = fork_mode if fork_mode != "none" else definition.fork_mode
        effective_isolation = (
            AgentIsolationMode(isolation_mode)
            if isolation_mode
            else definition.isolation_mode
        )
        effective_permission = (
            AgentPermissionMode(permission_mode)
            if permission_mode
            else definition.permission_mode
        )

        child_cwd = self._parent.cwd
        worktree_path: Path | None = None
        if effective_isolation == AgentIsolationMode.GIT_WORKTREE:
            worktree_path = self._worktrees.create(record.agent_id)
            if worktree_path is not None:
                child_cwd = worktree_path
            else:
                effective_isolation = AgentIsolationMode.SHARED_WORKSPACE

        record.cwd = str(child_cwd)
        record.worktree_path = str(worktree_path) if worktree_path else None
        record.definition_source = definition.source
        record.isolation_mode = effective_isolation.value
        record.permission_mode = effective_permission.value
        self._store.upsert_record(self._parent.session_id, record)

        child_session = self._make_child_session(
            model=model,
            fork_mode=effective_fork_mode,
            cwd=child_cwd,
            definition=definition,
            permission_mode=effective_permission,
        )

        agent = BobSubAgent(
            record=record,
            session=child_session,
            parent_session=self._parent,
            completion_queue=self._completion_queue,
            worktree_manager=self._worktrees if worktree_path is not None else None,
            run_store=self._store,
        )
        self._agents[record.agent_id] = agent
        agent.start()
        return record

    def _make_child_session(
        self,
        *,
        model: Optional[str],
        fork_mode: str,
        cwd: Path,
        definition: AgentDefinition,
        permission_mode: AgentPermissionMode,
    ) -> "BobSession":
        from bob.core.session import BobSession
        from bob.protocol.config_types import AskForApproval
        from bob.core.network_policy import NetworkPolicy

        parent = self._parent
        role_instructions = definition.instructions.strip()
        developer_instructions = (parent.config.developer_instructions or "").strip()
        if role_instructions:
            injected = f"# Agent Role: {definition.name}\n\n{role_instructions}"
            developer_instructions = (
                f"{developer_instructions}\n\n{injected}".strip()
                if developer_instructions
                else injected
            )

        overrides: dict = {
            "ask_for_approval": AskForApproval.NEVER,
            "developer_instructions": developer_instructions or None,
        }
        if model:
            overrides["model"] = model
        elif definition.model:
            overrides["model"] = definition.model

        child_config = parent.config.model_copy(update=overrides)
        child_session = BobSession(
            config=child_config,
            cwd=cwd,
            ephemeral=True,
        )
        child_session._network_policy = NetworkPolicy(network_access=True)

        if definition.allowed_tools:
            child_session._allowed_tools = set(definition.allowed_tools)
        if permission_mode == AgentPermissionMode.READ_ONLY:
            child_session._allow_mutating_tools = False

        if fork_mode != "none":
            history = list(parent.context_manager.raw_items())
            if fork_mode.startswith("last_n:"):
                try:
                    n = int(fork_mode.split(":", 1)[1])
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
        wait_tasks = []
        resolved: dict[str, AgentRecord] = {}

        for target in targets:
            record = await self._resolve_record(target)
            if record is None:
                continue
            resolved[target] = record
            wait_tasks.append(self._registry.wait_for(record.agent_id, timeout_ms=timeout_ms))

        if wait_tasks:
            await asyncio.gather(*wait_tasks, return_exceptions=True)

        results: dict[str, dict] = {}
        for target in targets:
            record = resolved.get(target) or await self._resolve_record(target)
            if record is None:
                stored = self._resolve_stored_record(target)
                if stored is not None:
                    results[stored["agent_id"]] = {
                        "status": stored["status"],
                        "result": stored["result"],
                        "error": stored["error"],
                        "tool_uses": stored["tool_uses"],
                        "tokens": stored["tokens"],
                        "agent_type": stored["agent_type"],
                        "cwd": stored["cwd"],
                        "worktree_path": stored["worktree_path"],
                        "merge_status": stored["merge_status"],
                        "merge_success": stored["merge_success"],
                    }
                    continue
                results[target] = {
                    "status": "not_found",
                    "result": None,
                    "error": "agent not found",
                }
                continue
            results[record.agent_id] = {
                "status": record.status.value,
                "result": record.result,
                "error": record.error,
                "tool_uses": record.progress.tool_use_count,
                "tokens": record.progress.token_count,
                "agent_type": record.agent_type,
                "cwd": record.cwd,
                "worktree_path": record.worktree_path,
                "merge_status": record.merge_status,
                "merge_success": record.merge_success,
            }
        return results

    async def close(self, target: str) -> Optional[str]:
        agent = self._find_agent(target)
        if agent is None:
            record = await self._resolve_record(target)
            return record.status.value if record else None
        record = self._registry._agents.get(agent.agent_id)
        previous = record.status.value if record else "unknown"
        agent.cancel()
        return previous

    async def list_agents(self) -> list[dict]:
        live = [
            {
                "agent_id": record.agent_id,
                "path": str(record.path),
                "name": record.path.name,
                "agent_type": record.agent_type,
                "task": record.task[:100],
                "status": record.status.value,
                "cwd": record.cwd,
                "worktree_path": record.worktree_path,
                "isolation_mode": record.isolation_mode,
                "permission_mode": record.permission_mode,
                "last_activity": record.progress.last_activity,
                "tool_uses": record.progress.tool_use_count,
                "tokens": record.progress.token_count,
                "merge_status": record.merge_status,
                "result_preview": (record.result or "")[:200] if record.result else None,
                "error": record.error,
                "created_at_ts": int(record.started_at * 1000) if record.started_at else None,
                "updated_at_ts": int(record.started_at * 1000) if record.started_at else None,
            }
            for record in await self._registry.list_all()
        ]
        merged: dict[str, dict] = {
            row["agent_id"]: row for row in self._store.list_for_thread(self._parent.session_id)
        }
        for row in live:
            merged[row["agent_id"]] = row
        return sorted(
            merged.values(),
            key=lambda row: int(row.get("created_at_ts", 0) or 0),
            reverse=True,
        )

    async def get_status(self, target: str) -> Optional[dict]:
        record = await self._resolve_record(target)
        if record is None:
            stored = self._resolve_stored_record(target)
            if stored is None:
                return None
            return stored
        return {
            "agent_id": record.agent_id,
            "path": str(record.path),
            "agent_type": record.agent_type,
            "status": record.status.value,
            "cwd": record.cwd,
            "worktree_path": record.worktree_path,
            "isolation_mode": record.isolation_mode,
            "permission_mode": record.permission_mode,
            "last_activity": record.progress.last_activity,
            "recent_activities": record.progress.recent_activities,
            "tool_uses": record.progress.tool_use_count,
            "tokens": record.progress.token_count,
            "merge_status": record.merge_status,
            "merge_success": record.merge_success,
            "result": record.result,
            "error": record.error,
            "created_at_ts": int(record.started_at * 1000) if record.started_at else None,
            "updated_at_ts": int(record.started_at * 1000) if record.started_at else None,
        }

    def count_active(self) -> int:
        return sum(
            1 for record in self._registry._agents.values()
            if not record.status.is_terminal
        )

    async def shutdown(self) -> None:
        for agent in list(self._agents.values()):
            agent.cancel()
        tasks = [
            agent._asyncio_task
            for agent in self._agents.values()
            if getattr(agent, "_asyncio_task", None) is not None
        ]
        for task in tasks:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

    def _resolve_definition(self, agent_type: str) -> AgentDefinition:
        definition = self._definitions.find(agent_type)
        if definition is not None:
            return definition
        fallback = self._definitions.find("worker")
        if fallback is None:
            raise RuntimeError("Default agent definition 'worker' is missing.")
        return fallback.model_copy(deep=True)

    def _find_agent(self, target: str) -> Optional[BobSubAgent]:
        if target in self._agents:
            return self._agents[target]
        for agent in self._agents.values():
            if agent.path.name == target or str(agent.path) == target:
                return agent
        return None

    async def _resolve_record(self, target: str) -> Optional[AgentRecord]:
        record = await self._registry.get(target)
        if record:
            return record
        return await self._registry.find_by_name(target)

    def _resolve_stored_record(self, target: str) -> Optional[dict]:
        stored = self._store.get(self._parent.session_id, target)
        if stored is not None:
            return stored
        return self._store.find_by_name(self._parent.session_id, target)


_COMMON_NAME_STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with",
    "this", "that", "these", "those", "please", "then", "after", "before", "use",
}


def derive_agent_name(task: str, *, fallback: str = "worker") -> str:
    words = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]+", task or "")
        if token and token.lower() not in _COMMON_NAME_STOPWORDS
    ]
    if not words:
        return fallback
    selected = words[:4]
    return "_".join(selected)
