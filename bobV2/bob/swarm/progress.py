from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _AgentRecord:
    agent_id: str
    role: str
    last_activity_ts: float = field(default_factory=time.time)
    turns: int = 0
    files_touched: int = 0
    stalled: bool = False
    completed: bool = False


class SwarmProgressTracker:
    """PAD-inspired stall detection and progress accounting for swarm agents.

    Pleasure (Progress): change in files_touched or turns over time.
    An agent that shows no progress for idle_timeout_seconds is flagged stalled.
    """

    def __init__(self, stall_threshold_seconds: float = 120.0):
        self._agents: dict[str, _AgentRecord] = {}
        self._stall_threshold = stall_threshold_seconds
        self._total = 0
        self._done = 0

    def register(self, agent_id: str, role: str) -> None:
        self._agents[agent_id] = _AgentRecord(agent_id=agent_id, role=role)
        self._total += 1

    def record_activity(self, agent_id: str, *, turns: int = 0, files: int = 0) -> None:
        rec = self._agents.get(agent_id)
        if rec is None:
            return
        rec.last_activity_ts = time.time()
        rec.turns += turns
        rec.files_touched += files

    def mark_done(self, agent_id: str) -> None:
        rec = self._agents.get(agent_id)
        if rec:
            rec.completed = True
            rec.stalled = False
        self._done += 1

    def check_stalls(self) -> list[str]:
        """Return ids of newly-detected stalled agents."""
        now = time.time()
        newly_stalled = []
        for rec in self._agents.values():
            if rec.completed or rec.stalled:
                continue
            if now - rec.last_activity_ts > self._stall_threshold:
                rec.stalled = True
                newly_stalled.append(rec.agent_id)
        return newly_stalled

    @property
    def total(self) -> int:
        return self._total

    @property
    def done(self) -> int:
        return self._done

    @property
    def running(self) -> int:
        return sum(
            1 for r in self._agents.values()
            if not r.completed and not r.stalled
        )

    @property
    def stalled(self) -> int:
        return sum(1 for r in self._agents.values() if r.stalled)

    def status_line(self, phase: str) -> str:
        parts = [f"[swarm:{phase}]",
                 f"{self._done}/{self._total} done"]
        if self.running:
            parts.append(f"{self.running} running")
        if self.stalled:
            parts.append(f"{self.stalled} stalled")
        return "  ".join(parts)
