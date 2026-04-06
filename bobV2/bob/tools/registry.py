from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

# Signature: async def handler(tool_input: dict, context: Any) -> str
ToolHandler = Callable[[dict, Any], Awaitable[str]]


@dataclass
class RegisteredTool:
    """Metadata + handler for a single registered tool."""

    name: str
    description: str
    input_schema: dict
    handler: ToolHandler
    parallel: bool = True


class ToolRegistry:
    """
    Central registry for all tools available to the agent.

    Tools are registered with a JSON Schema for their inputs and an async
    handler coroutine.  The registry converts registrations to the
    OpenAI function-calling spec format and dispatches incoming tool calls.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: ToolHandler,
        parallel: bool = True,
    ) -> None:
        """Register (or overwrite) a tool."""
        self._tools[name] = RegisteredTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            parallel=parallel,
        )

    def unregister(self, name: str) -> None:
        """Remove a tool by name (no-op if not registered)."""
        self._tools.pop(name, None)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_tool_specs(self) -> list[dict]:
        """
        Return tool specs in the OpenAI Responses API format (flat, not nested
        under "function" like Chat Completions)::

            [
                {
                    "type": "function",
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                },
                ...
            ]
        """
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def has_tool(self, name: str) -> bool:
        """Return True if *name* is currently registered."""
        return name in self._tools

    def list_tools(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self._tools.keys())

    def get_tool(self, name: str) -> Optional[RegisteredTool]:
        """Return the RegisteredTool for *name*, or None."""
        return self._tools.get(name)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, name: str, tool_input: dict, context: Any) -> str:
        """
        Invoke the handler for *name* with *tool_input* and *context*.

        Returns the string result of the handler, or a formatted error string
        if the tool is unknown or the handler raises.
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            result = await tool.handler(tool_input, context)
            return result if isinstance(result, str) else str(result)
        except Exception as exc:
            return f"Error executing tool '{name}': {exc}"
