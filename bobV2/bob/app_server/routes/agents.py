from __future__ import annotations

from bob.app_server.errors import invalid_params, not_found
from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import (
    AgentsCloseParams,
    AgentsGetParams,
    AgentsListParams,
    AgentsSpawnParams,
    AgentsWaitParams,
)


def _agent_control_or_raise(thread):
    agent_control = getattr(thread.session, "agent_control", None)
    if agent_control is None:
        raise invalid_params("Agent system not available for this thread", thread_id=thread.id)
    return agent_control


def register(router) -> None:
    async def agents_spawn(ctx, params: dict):
        p = parse_params(AgentsSpawnParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_control = _agent_control_or_raise(thread)
        prompt = (p.prompt or p.task or "").strip()
        if not prompt:
            raise invalid_params("prompt (or legacy task) is required", thread_id=p.thread_id)
        description = (p.description or "").strip() or None
        record = await agent_control.start_task(
            prompt,
            description=description,
            subagent_type=p.subagent_type or p.agent_type or "general",
            task_id=p.task_id,
            model=p.model,
            fork_mode=p.fork_mode,
            isolation_mode=p.isolation_mode,
            permission_mode=p.permission_mode,
            background=p.background,
        )
        return {
            "agent": {
                "task_id": record.agent_id,
                "agent_id": record.agent_id,
                "session_id": record.session_id,
                "path": str(record.path),
                "name": record.path.name,
                "title": record.title,
                "agent_type": record.agent_type,
                "task": record.task,
                "status": record.status.value,
                "cwd": record.cwd,
                "worktree_path": record.worktree_path,
                "isolation_mode": record.isolation_mode,
                "permission_mode": record.permission_mode,
                "background": record.background,
                "run_count": record.run_count,
            }
        }

    async def agents_get(ctx, params: dict):
        p = parse_params(AgentsGetParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_control = _agent_control_or_raise(thread)
        status = await agent_control.get_status(p.agent_id)
        if not status:
            raise not_found("Agent not found", thread_id=p.thread_id, agent_id=p.agent_id)
        return {"agent": status}

    async def agents_list(ctx, params: dict):
        p = parse_params(AgentsListParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_control = _agent_control_or_raise(thread)
        agents = await agent_control.list_agents()
        if not p.include_completed:
            agents = [a for a in agents if a.get("status") not in ("completed", "errored", "shutdown")]
        return {"agents": agents}

    async def agents_wait(ctx, params: dict):
        p = parse_params(AgentsWaitParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_control = _agent_control_or_raise(thread)
        targets = list(p.task_ids or []) + list(p.agent_ids or [])
        if not targets:
            raise invalid_params("task_ids or agent_ids must be a non-empty list")
        results = await agent_control.wait_for(targets, timeout_ms=p.timeout_ms)
        return {"results": results}

    async def agents_close(ctx, params: dict):
        p = parse_params(AgentsCloseParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_control = _agent_control_or_raise(thread)
        prev_status = await agent_control.close(p.target)
        if prev_status is None:
            raise not_found("Agent not found", thread_id=p.thread_id, target=p.target)
        return {"status": "ok", "previous_status": prev_status}

    router.add("agents.spawn", agents_spawn)
    router.add("agents.get", agents_get)
    router.add("agents.list", agents_list)
    router.add("agents.wait", agents_wait)
    router.add("agents.close", agents_close)
