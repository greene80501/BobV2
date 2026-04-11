from __future__ import annotations


def register(router) -> None:
    async def ping(ctx, params: dict):
        return {"pong": True}

    async def session_create(ctx, params: dict):
        out = await ctx.router.dispatch(ctx, "threads.create", params or {})
        thread_id = out["thread"]["id"]
        return {"session_id": thread_id, "status": "created"}

    async def session_submit(ctx, params: dict):
        thread_id = str(params.get("session_id") or params.get("thread_id") or "")
        text = str(params.get("text") or params.get("prompt") or "")
        items = params.get("items") or ([{"type": "text", "text": text}] if text else [])
        out = await ctx.router.dispatch(
            ctx,
            "turns.submit",
            {
                "thread_id": thread_id,
                "items": items,
                "developer_message_override": params.get("developer_message_override"),
            },
        )
        return {"status": "queued", "submission_id": out["turn"]["submission_id"]}

    async def session_interrupt(ctx, params: dict):
        thread_id = str(params.get("session_id") or params.get("thread_id") or "")
        await ctx.router.dispatch(ctx, "turns.interrupt", {"thread_id": thread_id, "graceful": True})
        return {"status": "ok"}

    async def session_shutdown(ctx, params: dict):
        thread_id = str(params.get("session_id") or params.get("thread_id") or "")
        ok = await ctx.registry.close_thread(thread_id, reason="legacy_shutdown")
        return {"status": "ok" if ok else "not_found"}

    router.add("ping", ping)
    router.add("bob.session.create", session_create)
    router.add("bob.session.submit", session_submit)
    router.add("bob.session.interrupt", session_interrupt)
    router.add("bob.session.shutdown", session_shutdown)

