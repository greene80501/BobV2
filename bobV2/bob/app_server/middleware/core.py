from __future__ import annotations

from typing import Any, Awaitable, Callable

Middleware = Callable[[Any, Any, Callable[[], Awaitable[Any]]], Awaitable[Any]]


async def run_middleware_chain(
    ctx: Any,
    request: Any,
    endpoint: Callable[[], Awaitable[Any]],
    middleware: list[Middleware],
) -> Any:
    async def _call(i: int) -> Any:
        if i >= len(middleware):
            return await endpoint()
        return await middleware[i](ctx, request, lambda: _call(i + 1))

    return await _call(0)

