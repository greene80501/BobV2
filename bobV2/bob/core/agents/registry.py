from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERRORED = "errored"
    INTERRUPTED = "interrupted"
    SHUTDOWN = "shutdown"

    @property
    def is_terminal(self) -> bool:
        return self in (AgentStatus.COMPLETED, AgentStatus.ERRORED, AgentStatus.SHUTDOWN)


@dataclass
class AgentProgress:
    tool_use_count: int = 0
    token_count: int = 0
    last_activity: str = ""
    recent_activities: list[str] = field(default_factory=list)

    def record_tool(self, tool_name: str, detail: str = "") -> None:
        self.tool_use_count += 1
        activity = tool_name + (f": {detail}" if detail else "")
        self.last_activity = activity
        self.recent_activities = (self.recent_activities[-4:] + [activity])


@dataclass
class AgentRecord:
    agent_id: str
    path: "AgentPath"
    task: str
    status: AgentStatus = AgentStatus.PENDING
    progress: AgentProgress = field(default_factory=AgentProgress)
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: float = 0.0
    _done_event: asyncio.Event = field(default_factory=asyncio.Event)


class AgentPath:
    """Hierarchical agent path: /root, /root/researcher, /root/planner."""

    def __init__(self, segments: tuple[str, ...]) -> None:
        self._segments = segments

    @classmethod
    def root(cls) -> "AgentPath":
        return cls(("root",))

    @classmethod
    def parse(cls, path: str) -> "AgentPath":
        parts = [p for p in path.strip("/").split("/") if p]
        return cls(tuple(parts)) if parts else cls.root()

    def join(self, name: str) -> "AgentPath":
        clean = re.sub(r"[^a-z0-9_]", "_", name.lower())[:32].lstrip("_") or "agent"
        if not clean[0].isalpha():
            clean = "a" + clean
        return AgentPath(self._segments + (clean,))

    @property
    def depth(self) -> int:
        return len(self._segments) - 1

    @property
    def name(self) -> str:
        return self._segments[-1]

    def __str__(self) -> str:
        return "/" + "/".join(self._segments)

    def __repr__(self) -> str:
        return f"AgentPath({str(self)!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AgentPath) and self._segments == other._segments

    def __hash__(self) -> int:
        return hash(self._segments)


class AgentRegistry:
    """Global registry for active sub-agents. Enforces concurrency and depth limits."""

    def __init__(self, max_agents: int = 8, max_depth: int = 1) -> None:
        self.max_agents = max_agents
        self.max_depth = max_depth
        self._agents: dict[str, AgentRecord] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, path: AgentPath, task: str) -> AgentRecord:
        async with self._lock:
            active = [r for r in self._agents.values() if not r.status.is_terminal]
            if len(active) >= self.max_agents:
                raise RuntimeError(
                    f"Agent limit reached ({self.max_agents} active). "
                    "Wait for agents to complete before spawning more."
                )
            if path.depth > self.max_depth:
                raise RuntimeError(
                    f"Max agent depth ({self.max_depth}) exceeded. "
                    "Sub-agents cannot spawn further agents."
                )
            agent_id = uuid.uuid4().hex[:8]
            record = AgentRecord(agent_id=agent_id, path=path, task=task)
            self._agents[agent_id] = record
            return record

    async def update_status(
        self,
        agent_id: str,
        status: AgentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            rec = self._agents.get(agent_id)
            if rec is None:
                return
            rec.status = status
            if result is not None:
                rec.result = result
            if error is not None:
                rec.error = error
            if status.is_terminal:
                rec._done_event.set()

    def update_progress(self, agent_id: str, progress: AgentProgress) -> None:
        rec = self._agents.get(agent_id)
        if rec:
            rec.progress = progress

    async def get(self, agent_id: str) -> Optional[AgentRecord]:
        return self._agents.get(agent_id)

    async def find_by_name(self, name: str) -> Optional[AgentRecord]:
        for rec in self._agents.values():
            if rec.path.name == name or str(rec.path) == name:
                return rec
        return None

    async def list_all(self) -> list[AgentRecord]:
        return list(self._agents.values())

    async def wait_for(self, agent_id: str, timeout_ms: int = 300_000) -> Optional[AgentRecord]:
        rec = self._agents.get(agent_id)
        if rec is None:
            return None
        if rec.status.is_terminal:
            return rec
        try:
            await asyncio.wait_for(rec._done_event.wait(), timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            pass
        return rec
