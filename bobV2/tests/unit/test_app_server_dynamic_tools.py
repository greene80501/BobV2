from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bob.app_server.router import RpcRouter
from bob.app_server.routes import dynamic_tools as dynamic_tools_routes
from bob.protocol.ops import DynamicToolResponseOp
from bob.tools.registry import ToolRegistry


class _FakeEventBus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, channels, payload):
        self.events.append((channels, payload))


@dataclass
class _FakeThread:
    session: object


class _FakeRegistry:
    def __init__(self, thread):
        self._thread = thread

    async def get_thread_or_raise(self, _thread_id: str):
        return self._thread


class _FakeSession:
    def __init__(self) -> None:
        self.tool_registry = ToolRegistry()
        self.submitted = []

    async def request_dynamic_tool(self, tool_call_id: str, tool_name: str, tool_input: dict, timeout_seconds: float = 120.0) -> str:
        return f"dynamic:{tool_name}:{tool_call_id}:{tool_input.get('x')}"

    async def submit(self, op):
        self.submitted.append(op)


class _FakeCtx:
    def __init__(self, registry, event_bus):
        self.registry = registry
        self.event_bus = event_bus


def test_dynamic_tools_register_search_enable_and_respond() -> None:
    router = RpcRouter()
    dynamic_tools_routes.register(router)

    sess = _FakeSession()
    thread = _FakeThread(session=sess)
    ctx = _FakeCtx(_FakeRegistry(thread), _FakeEventBus())

    register_res = asyncio.run(
        router.dispatch(
            ctx,
            "dynamic_tools.register",
            {
                "thread_id": "t1",
                "tools": [
                    {
                        "name": "app_fetch",
                        "description": "Fetch from app",
                        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
                        "source": "app",
                        "expose_to_model": False,
                        "discoverable": True,
                        "is_mutating": False,
                        "supports_parallel": True,
                        "keywords": ["crm"],
                    }
                ],
            },
        )
    )
    assert register_res["registered"] == ["app_fetch"]
    assert sess.tool_registry.get_tool_capabilities("app_fetch").expose_to_model is False

    search_res = asyncio.run(
        router.dispatch(
            ctx,
            "dynamic_tools.search",
            {
                "thread_id": "t1",
                "query": "crm",
                "sources": ["app"],
                "auto_enable": True,
            },
        )
    )
    assert search_res["enabled"] == ["app_fetch"]
    assert sess.tool_registry.get_tool_capabilities("app_fetch").expose_to_model is True

    enable_res = asyncio.run(
        router.dispatch(
            ctx,
            "dynamic_tools.enable",
            {
                "thread_id": "t1",
                "tool_names": ["app_fetch"],
                "expose_to_model": False,
            },
        )
    )
    assert enable_res["enabled"] == ["app_fetch"]
    assert sess.tool_registry.get_tool_capabilities("app_fetch").expose_to_model is False

    respond_res = asyncio.run(
        router.dispatch(
            ctx,
            "dynamic_tools.respond",
            {
                "thread_id": "t1",
                "tool_call_id": "call-1",
                "result": {"ok": True},
            },
        )
    )
    assert respond_res["status"] == "ok"
    assert isinstance(sess.submitted[-1], DynamicToolResponseOp)
    assert sess.submitted[-1].tool_call_id == "call-1"
