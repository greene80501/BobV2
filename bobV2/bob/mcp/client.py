from __future__ import annotations
import asyncio
from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict
    server_name: str


class McpServerConnection:
    """Manages connection to a single MCP server subprocess."""

    def __init__(self, name: str, command: list[str], env: dict[str, str] = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self._session = None
        self._stdio_ctx = None
        self._tools: list[McpTool] = []
        self._connected = False

    async def connect(self) -> bool:
        """Spawn the server process and connect via stdio. Returns True on success."""
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            import os

            env = os.environ.copy()
            env.update(self.env)

            server_params = StdioServerParameters(
                command=self.command[0],
                args=self.command[1:],
                env=env,
            )

            self._stdio_ctx = stdio_client(server_params)
            read_stream, write_stream = await self._stdio_ctx.__aenter__()
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

            tools_result = await self._session.list_tools()
            self._tools = [
                McpTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                    server_name=self.name,
                )
                for tool in tools_result.tools
            ]

            self._connected = True
            return True

        except ImportError:
            # MCP SDK not installed — silently skip
            self._connected = False
            return False
        except Exception:
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._stdio_ctx:
            try:
                await self._stdio_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_ctx = None
        self._connected = False

    async def list_tools(self) -> list[McpTool]:
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self._session or not self._connected:
            return "Error: not connected to MCP server"
        try:
            result = await self._session.call_tool(tool_name, arguments)
            # Extract text content from result
            if hasattr(result, "content"):
                texts = [
                    item.text
                    for item in result.content
                    if hasattr(item, "text")
                ]
                return "\n".join(texts)
            return str(result)
        except Exception as exc:
            return f"Error calling MCP tool '{tool_name}' on server '{self.name}': {exc}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    # Async context manager support
    async def __aenter__(self) -> "McpServerConnection":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()
