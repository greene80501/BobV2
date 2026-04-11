from __future__ import annotations

from bob.app_server.errors import invalid_params
from bob.app_server.routes._utils import parse_params
from bob.protocol.v1.events import RealtimeEventEnvelope
from bob.protocol.v1.requests import RealtimeReplayParams, RealtimeSubscribeParams, RealtimeUnsubscribeParams


def register(router) -> None:
    async def realtime_subscribe(ctx, params: dict):
        if ctx.connection is None:
            raise invalid_params("realtime.subscribe requires websocket transport")
        p = parse_params(RealtimeSubscribeParams, params)
        sub_id, queue = await ctx.event_bus.subscribe(p.channels)
        ctx.connection.subscriptions[sub_id] = {"channels": p.channels, "queue": queue}
        return {"subscription_id": sub_id}

    async def realtime_unsubscribe(ctx, params: dict):
        if ctx.connection is None:
            raise invalid_params("realtime.unsubscribe requires websocket transport")
        p = parse_params(RealtimeUnsubscribeParams, params)
        ok = await ctx.event_bus.unsubscribe(p.subscription_id)
        ctx.connection.subscriptions.pop(p.subscription_id, None)
        return {"status": "ok" if ok else "not_found"}

    async def realtime_replay(ctx, params: dict):
        p = parse_params(RealtimeReplayParams, params)
        records = await ctx.event_bus.replay(
            channels=p.channels,
            after_cursor=p.after_cursor,
            limit=p.limit,
        )
        return {
            "events": [
                RealtimeEventEnvelope(
                    subscription_id="replay",
                    cursor=r.cursor,
                    channels=r.channels,
                    event=r.event,
                ).model_dump()
                for r in records
            ]
        }

    router.add("realtime.subscribe", realtime_subscribe)
    router.add("realtime.unsubscribe", realtime_unsubscribe)
    router.add("realtime.replay", realtime_replay)

