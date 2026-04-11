from __future__ import annotations

from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import (
    AgentsCloseParams,
    AgentsListParams,
    AgentsSendParams,
    AgentsSpawnParams,
    AgentsWaitParams,
)


def register(router) -> None:
    async def agents_spawn(ctx, params: dict):
        p = parse_params(AgentsSpawnParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_id = await ctx.agent_runtime.manager.spawn(
            session=thread.session,
            task=p.task,
            mode=p.mode,
            model=p.model,
            cwd=p.cwd,
            name=p.name,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{agent_id}"],
            {"thread_id": p.thread_id, "agent_id": agent_id, "event": {"type": "agent.spawned"}},
        )
        return {"agent_id": agent_id}

    async def agents_send(ctx, params: dict):
        p = parse_params(AgentsSendParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        result = await ctx.agent_runtime.manager.send(
            session=thread.session,
            agent_id=p.agent_id,
            message=p.message,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{p.agent_id}"],
            {"thread_id": p.thread_id, "agent_id": p.agent_id, "event": {"type": "agent.message_sent"}},
        )
        return {"status": "ok", "message": result}

    async def agents_wait(ctx, params: dict):
        p = parse_params(AgentsWaitParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        result = await ctx.agent_runtime.manager.wait(
            session=thread.session,
            agent_id=p.agent_id,
            timeout_seconds=p.timeout_seconds,
        )
        return {"result": result}

    async def agents_close(ctx, params: dict):
        p = parse_params(AgentsCloseParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        await ctx.agent_runtime.manager.close(
            session=thread.session,
            agent_id=p.agent_id,
            reason=p.reason,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{p.agent_id}"],
            {"thread_id": p.thread_id, "agent_id": p.agent_id, "event": {"type": "agent.closed"}},
        )
        return {"status": "ok"}

    async def agents_list(ctx, params: dict):
        p = parse_params(AgentsListParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agents = await ctx.agent_runtime.manager.list(
            session=thread.session,
            include_completed=p.include_completed,
        )
        return {"agents": agents}

    router.add("agents.spawn", agents_spawn)
    router.add("agents.send", agents_send)
    router.add("agents.wait", agents_wait)
    router.add("agents.close", agents_close)
    router.add("agents.list", agents_list)

