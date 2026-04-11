from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable

from bob.app_server.errors import unauthorized


async def auth_middleware(ctx: Any, request: Any, call_next: Callable[[], Awaitable[Any]]) -> Any:
    expected = os.environ.get("BOB_APP_SERVER_TOKEN", "")
    if not expected:
        return await call_next()

    token = ""
    if isinstance(request.params, dict):
        token = str(request.params.get("_auth_token", ""))
    if token != expected:
        raise unauthorized()
    return await call_next()


async def validation_middleware(ctx: Any, request: Any, call_next: Callable[[], Awaitable[Any]]) -> Any:
    if request.jsonrpc != "2.0":
        from bob.app_server.errors import AppServerError

        raise AppServerError(-32600, "Invalid JSON-RPC version")
    if not isinstance(request.method, str) or not request.method:
        from bob.app_server.errors import AppServerError

        raise AppServerError(-32600, "Invalid method")
    if request.params is None:
        request.params = {}
    if not isinstance(request.params, dict):
        from bob.app_server.errors import AppServerError

        raise AppServerError(-32602, "params must be an object")
    return await call_next()


async def tracing_middleware(ctx: Any, request: Any, call_next: Callable[[], Awaitable[Any]]) -> Any:
    started = time.monotonic()
    try:
        return await call_next()
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        if hasattr(ctx, "logger") and ctx.logger:
            ctx.logger(f"[app-server] method={request.method} duration_ms={duration_ms}")

