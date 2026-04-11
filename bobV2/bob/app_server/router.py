from __future__ import annotations

from typing import Any, Awaitable, Callable

from bob.app_server.errors import AppServerError

Handler = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any] | list | str | int | float | bool | None]]


class RpcRouter:
    def __init__(self) -> None:
        self._routes: dict[str, Handler] = {}

    def add(self, method: str, handler: Handler) -> None:
        self._routes[method] = handler

    @property
    def methods(self) -> list[str]:
        return sorted(self._routes.keys())

    async def dispatch(self, ctx: Any, method: str, params: dict[str, Any]) -> Any:
        handler = self._routes.get(method)
        if handler is None:
            raise AppServerError(-32601, f"Method not found: {method!r}")
        return await handler(ctx, params)

