from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bob.app_server.errors import invalid_params
from bob.core.agents.modes import MODES


@dataclass
class AgentPolicy:
    max_agents: int = 8
    allowed_cwds: list[str] | None = None
    allowed_tools: list[str] | None = None


class AgentManager:
    def __init__(self, policy: Optional[AgentPolicy] = None) -> None:
        self.policy = policy or AgentPolicy()

    async def spawn(
        self,
        *,
        session,
        task: str,
        mode: Optional[str] = None,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        mode_name = (mode or "default").strip().lower()
        mode_cfg = MODES.get(mode_name)
        if mode_cfg is None:
            raise invalid_params("Unknown collaboration mode", mode=mode_name)

        thread_manager = session.ensure_thread_manager()
        active = thread_manager.list_agents(include_completed=False)
        if len(active) >= min(self.policy.max_agents, mode_cfg.max_agents):
            raise invalid_params("Agent limit reached", max_agents=self.policy.max_agents)

        if cwd and self.policy.allowed_cwds:
            if cwd not in self.policy.allowed_cwds:
                raise invalid_params("cwd is not allowed by policy", cwd=cwd)

        return await thread_manager.spawn(
            task=task,
            model=model,
            cwd=cwd,
            template=mode_cfg.template,
            name=name,
        )

    async def send(self, *, session, agent_id: str, message: str) -> str:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.send_message(agent_id, message)

    async def wait(self, *, session, agent_id: str, timeout_seconds: Optional[float]) -> Optional[str]:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.wait_for_agent(agent_id, timeout=timeout_seconds)

    async def close(self, *, session, agent_id: str, reason: Optional[str]) -> None:
        thread_manager = session.ensure_thread_manager()
        await thread_manager.close_agent(agent_id, reason=reason)

    async def list(self, *, session, include_completed: bool) -> list[dict]:
        thread_manager = session.ensure_thread_manager()
        return thread_manager.list_agents(include_completed=include_completed)

