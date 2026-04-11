from __future__ import annotations

from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import ThreadsCreateParams, ThreadsGetParams, ThreadsListParams


def register(router) -> None:
    async def threads_create(ctx, params: dict):
        p = parse_params(ThreadsCreateParams, params)
        thread = await ctx.registry.create_thread(
            cwd=p.cwd,
            model=p.model,
            name=p.name,
            ephemeral=p.ephemeral,
        )
        return {"thread": thread.to_dict()}

    async def threads_get(ctx, params: dict):
        p = parse_params(ThreadsGetParams, params)
        thread = await ctx.registry.get_thread_or_raise(p.thread_id)
        return {"thread": thread.to_dict()}

    async def threads_list(ctx, params: dict):
        p = parse_params(ThreadsListParams, params)
        threads = await ctx.registry.list_threads()
        if p.cwd:
            threads = [t for t in threads if t.cwd == p.cwd]
        if p.offset:
            threads = threads[p.offset :]
        threads = threads[: max(1, min(p.limit, 500))]
        return {"threads": [t.to_dict() for t in threads]}

    router.add("threads.create", threads_create)
    router.add("threads.get", threads_get)
    router.add("threads.list", threads_list)

