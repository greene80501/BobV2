from __future__ import annotations

from bob.tools.registry import ToolRegistry


async def _dummy_handler(_tool_input: dict, _context) -> str:
    return "ok"


def test_registry_capabilities_default_conservative() -> None:
    reg = ToolRegistry()
    reg.register("x", "desc", {"type": "object"}, _dummy_handler)

    caps = reg.get_tool_capabilities("x")
    assert caps.is_mutating is True
    assert caps.supports_parallel is False
    assert caps.requires_network_approval is False
    assert caps.emits_exec_events is False


def test_registry_capabilities_explicit_flags() -> None:
    reg = ToolRegistry()
    reg.register(
        "read_tool",
        "desc",
        {"type": "object"},
        _dummy_handler,
        is_mutating=False,
        supports_parallel=True,
        requires_network_approval=True,
    )

    caps = reg.get_tool_capabilities("read_tool")
    assert caps.is_mutating is False
    assert caps.supports_parallel is True
    assert caps.requires_network_approval is True


def test_registry_parallel_backcompat_parameter() -> None:
    reg = ToolRegistry()
    reg.register("legacy", "desc", {"type": "object"}, _dummy_handler, parallel=True)
    caps = reg.get_tool_capabilities("legacy")
    assert caps.supports_parallel is True
