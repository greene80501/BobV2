from __future__ import annotations

from typing import Any

__all__ = ["run_server"]


async def run_server(*args: Any, **kwargs: Any) -> Any:
    from bob.app_server.server import run_server as _run_server

    return await _run_server(*args, **kwargs)
