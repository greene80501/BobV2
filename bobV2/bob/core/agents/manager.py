from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bob.app_server.errors import invalid_params
from bob.core.agents.modes import MODES


@dataclass
class AgentPolicy:
    max_agents: int = 8
    max_depth: int = 5
    max_runtime_seconds: int = 3600
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
        parent_agent_id: Optional[str] = None,
        role: Optional[str] = None,
        task_name: Optional[str] = None,
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

        allowed_tools: list[str] | None = None
        if self.policy.allowed_tools is not None:
            allowed_tools = list(self.policy.allowed_tools)

        if mode_cfg.template:
            from bob.core.agent_templates import get_template

            tmpl = get_template(mode_cfg.template)
            if tmpl and tmpl.allowed_tools:
                tmpl_allowed = set(tmpl.allowed_tools)
                if allowed_tools is None:
                    allowed_tools = sorted(tmpl_allowed)
                else:
                    allowed_tools = sorted(tmpl_allowed.intersection(allowed_tools))

        runtime_ttl_seconds = min(
            int(mode_cfg.max_runtime_seconds),
            int(self.policy.max_runtime_seconds),
        )
        if runtime_ttl_seconds <= 0:
            runtime_ttl_seconds = int(mode_cfg.max_runtime_seconds)

        return await thread_manager.spawn(
            task=task,
            model=model,
            cwd=cwd,
            template=mode_cfg.template,
            name=name,
            parent_agent_id=parent_agent_id,
            role=role,
            max_depth=self.policy.max_depth,
            allowed_tools=allowed_tools,
            runtime_ttl_seconds=runtime_ttl_seconds,
            allow_mutating_tools=mode_cfg.allow_mutating_tools,
            task_name=task_name,
        )

    async def send(self, *, session, agent_id: str, message: str) -> str:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.send_message(agent_id, message)

    async def wait(self, *, session, agent_id: str, timeout_seconds: Optional[float]) -> Optional[str]:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.wait_for_agent(agent_id, timeout=timeout_seconds)

    async def wait_many(
        self,
        *,
        session,
        agent_refs: list[str],
        timeout_seconds: Optional[float],
        any_target: bool = True,
        wait_for_states: Optional[set[str]] = None,
    ) -> dict:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.wait_for_agents(
            agent_refs,
            timeout=timeout_seconds,
            any_target=any_target,
            wait_for_states=wait_for_states,
        )

    async def close(self, *, session, agent_id: str, reason: Optional[str]) -> None:
        thread_manager = session.ensure_thread_manager()
        await thread_manager.close_agent(agent_id, reason=reason)

    async def assign(
        self,
        *,
        session,
        agent_id: str,
        task: str,
        task_name: Optional[str] = None,
        interrupt_running: bool = False,
        clear_queue: bool = False,
    ) -> dict:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.assign_task(
            agent_id=agent_id,
            task=task,
            task_name=task_name,
            interrupt_running=interrupt_running,
            clear_queue=clear_queue,
        )

    async def resume(self, *, session, agent_id: str, task: Optional[str] = None) -> dict:
        thread_manager = session.ensure_thread_manager()
        return await thread_manager.resume_agent(agent_id=agent_id, task=task)

    async def list(self, *, session, include_completed: bool) -> list[dict]:
        thread_manager = session.ensure_thread_manager()
        return thread_manager.list_agents(include_completed=include_completed)
