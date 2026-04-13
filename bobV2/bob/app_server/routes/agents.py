from __future__ import annotations

from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import (
    AgentsAssignParams,
    AgentsCloseParams,
    AgentsListParams,
    AgentsResumeParams,
    AgentsSendParams,
    AgentsSpawnParams,
    AgentsWaitParams,
)


def register(router) -> None:
    async def agents_spawn(ctx, params: dict):
        p = parse_params(AgentsSpawnParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        parent_ref = p.parent_agent_ref or p.parent_agent_id
        agent_id = await ctx.agent_runtime.manager.spawn(
            session=thread.session,
            task=p.task,
            mode=p.mode,
            model=p.model,
            cwd=p.cwd,
            name=p.name,
            parent_agent_id=parent_ref,
            role=p.role,
            task_name=getattr(p, "task_name", None),
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{agent_id}"],
            {"thread_id": p.thread_id, "agent_id": agent_id, "event": {"type": "agent.spawned"}},
        )
        return {"agent_id": agent_id}

    async def agents_send(ctx, params: dict):
        p = parse_params(AgentsSendParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_ref = (p.agent_ref or p.agent_id or "").strip()
        if not agent_ref:
            return {"error": "agent_ref or agent_id is required"}
        result = await ctx.agent_runtime.manager.send(
            session=thread.session,
            agent_id=agent_ref,
            message=p.message,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{agent_ref}"],
            {"thread_id": p.thread_id, "agent_id": agent_ref, "event": {"type": "agent.message_sent"}},
        )
        return {"status": "ok", "message": result}

    async def agents_wait(ctx, params: dict):
        p = parse_params(AgentsWaitParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_refs = list(p.agent_ids or [])
        if p.agent_id:
            agent_refs = [p.agent_id, *[x for x in agent_refs if x != p.agent_id]]
        if not agent_refs:
            return {"error": "agent_id or agent_ids is required"}
        result = await ctx.agent_runtime.manager.wait_many(
            session=thread.session,
            agent_refs=agent_refs,
            timeout_seconds=p.timeout_seconds,
            any_target=p.any_target,
            wait_for_states=set(p.wait_for_states or []),
        )
        return result

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

    async def agents_assign(ctx, params: dict):
        p = parse_params(AgentsAssignParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        agent_ref = (p.agent_ref or p.agent_id or "").strip()
        if not agent_ref:
            return {"error": "agent_ref or agent_id is required"}
        snapshot = await ctx.agent_runtime.manager.assign(
            session=thread.session,
            agent_id=agent_ref,
            task=p.task,
            task_name=p.task_name,
            interrupt_running=p.interrupt_running,
            clear_queue=p.clear_queue,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{snapshot.get('id', agent_ref)}"],
            {
                "thread_id": p.thread_id,
                "agent_id": snapshot.get("id", agent_ref),
                "event": {"type": "agent.task_assigned", "task": p.task, "task_name": p.task_name},
            },
        )
        return {"agent": snapshot}

    async def agents_resume(ctx, params: dict):
        p = parse_params(AgentsResumeParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        snapshot = await ctx.agent_runtime.manager.resume(
            session=thread.session,
            agent_id=p.agent_id,
            task=p.task,
        )
        await ctx.event_bus.publish(
            [f"thread:{p.thread_id}", f"agent:{snapshot.get('id', p.agent_id)}"],
            {"thread_id": p.thread_id, "agent_id": snapshot.get("id", p.agent_id), "event": {"type": "agent.resumed"}},
        )
        return {"agent": snapshot}

    router.add("agents.spawn", agents_spawn)
    router.add("agents.send", agents_send)
    router.add("agents.wait", agents_wait)
    router.add("agents.close", agents_close)
    router.add("agents.list", agents_list)
    router.add("agents.assign", agents_assign)
    router.add("agents.resume", agents_resume)
