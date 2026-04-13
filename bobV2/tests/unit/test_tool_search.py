from __future__ import annotations

import asyncio

from bob.tools.registry import ToolRegistry
from bob.tools.tool_search import tool_search_handler


async def _dummy(_tool_input: dict, _context) -> str:
    return "ok"


class _Ctx:
    def __init__(self, registry: ToolRegistry) -> None:
        self._session = type("S", (), {"tool_registry": registry})()


def test_tool_search_can_find_and_enable_hidden_tools() -> None:
    reg = ToolRegistry()
    reg.register(
        "app_lookup",
        "Lookup records in an app connector",
        {"type": "object", "properties": {}},
        _dummy,
        is_mutating=False,
        supports_parallel=True,
        expose_to_model=False,
        discoverable=True,
        source="app",
        keywords=["crm", "contacts"],
    )

    ctx = _Ctx(reg)
    out = asyncio.run(
        tool_search_handler(
            {
                "query": "crm",
                "sources": ["app"],
                "auto_enable": True,
            },
            ctx,
        )
    )

    assert "app_lookup" in out
    assert "Enabled 1 tool(s): app_lookup" in out
    assert reg.get_tool_capabilities("app_lookup").expose_to_model is True
