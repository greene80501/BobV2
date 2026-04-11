from __future__ import annotations

from bob.app_server.errors import not_found
from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.requests import (
    HistoryReadParams,
    TurnsCancelParams,
    TurnsGetParams,
    TurnsInterruptParams,
    TurnsListParams,
    TurnsSubmitParams,
)


def register(router) -> None:
    async def turns_submit(ctx, params: dict):
        p = parse_params(TurnsSubmitParams, params)
        turn = await ctx.registry.submit_turn(
            thread_id=p.thread_id,
            items=p.items,
            developer_message_override=p.developer_message_override,
        )
        return {"turn": turn.to_dict()}

    async def turns_get(ctx, params: dict):
        p = parse_params(TurnsGetParams, params)
        turn = await ctx.registry.get_turn(p.thread_id, p.turn_id)
        if not turn:
            raise not_found("Turn not found", thread_id=p.thread_id, turn_id=p.turn_id)
        return {"turn": turn.to_dict()}

    async def turns_list(ctx, params: dict):
        p = parse_params(TurnsListParams, params)
        turns = await ctx.registry.list_turns(p.thread_id, limit=p.limit)
        return {"turns": [t.to_dict() for t in turns]}

    async def turns_interrupt(ctx, params: dict):
        p = parse_params(TurnsInterruptParams, params)
        await ctx.registry.interrupt_turn(p.thread_id, graceful=p.graceful)
        return {"status": "ok"}

    async def turns_cancel(ctx, params: dict):
        p = parse_params(TurnsCancelParams, params)
        await ctx.registry.interrupt_turn(p.thread_id, graceful=False)
        return {"status": "ok"}

    async def history_read(ctx, params: dict):
        p = parse_params(HistoryReadParams, params)
        items = await ctx.registry.history(p.thread_id, limit=p.limit)
        return {"items": items}

    router.add("turns.submit", turns_submit)
    router.add("turns.get", turns_get)
    router.add("turns.list", turns_list)
    router.add("turns.interrupt", turns_interrupt)
    router.add("turns.cancel", turns_cancel)
    router.add("history.read", history_read)

