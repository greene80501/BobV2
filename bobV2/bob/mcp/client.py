from __future__ import annotations
import asyncio
import os
import re
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict
    server_name: str


@dataclass
class McpResource:
    uri: str
    name: str
    description: str
    mime_type: str
    server_name: str


def _substitute_vars(text: str, extra_env: dict[str, str] | None = None) -> str:
    """Replace ${VAR} placeholders using environment variables and extra_env."""
    env = {**os.environ}
    if extra_env:
        env.update(extra_env)

    def _replace(m: re.Match) -> str:
        return env.get(m.group(1), m.group(0))

    return re.sub(r"\$\{([^}]+)\}", _replace, text)


def _substitute_vars_in_dict(d: dict, extra_env: dict[str, str] | None = None) -> dict:
    """Recursively substitute ${VAR} in all string values of a dict."""
    result: dict = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _substitute_vars(v, extra_env)
        elif isinstance(v, dict):
            result[k] = _substitute_vars_in_dict(v, extra_env)
        elif isinstance(v, list):
            result[k] = [
                _substitute_vars(item, extra_env) if isinstance(item, str) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


class McpServerConnection:
    """Manages a connection to a single MCP server (stdio, SSE, or HTTP)."""

    def __init__(
        self,
        name: str,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        transport: str = "stdio",
        url: str = "",
        headers: dict[str, str] | None = None,
        connect_timeout_seconds: float = 15.0,
        call_timeout_seconds: float = 30.0,
        retry_count: int = 1,
        max_output_chars: int = 32000,
    ):
        self.name = name
        self.transport = transport
        self.command = command or []
        self.env = env or {}
        self.url = url
        self.headers = headers or {}
        self.connect_timeout_seconds = max(1.0, min(float(connect_timeout_seconds), 120.0))
        self.call_timeout_seconds = max(1.0, min(float(call_timeout_seconds), 300.0))
        self.retry_count = max(0, min(int(retry_count), 5))
        self.max_output_chars = max(512, min(int(max_output_chars), 100_000))
        self._session = None
        self._transport_ctx = None
        self._tools: list[McpTool] = []
        self._resources: list[McpResource] = []
        self._connected = False

    async def connect(self) -> bool:
        try:
            if self.transport == "stdio":
                return await self._connect_stdio()
            elif self.transport == "sse":
                return await self._connect_sse()
            elif self.transport == "http":
                return await self._connect_http()
            else:
                return False
        except ImportError:
            self._connected = False
            return False
        except Exception:
            self._connected = False
            return False

    async def _connect_stdio(self) -> bool:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        merged_env = os.environ.copy()
        merged_env.update(self.env)

        command = [_substitute_vars(c, self.env) for c in self.command]
        server_params = StdioServerParameters(
            command=command[0] if command else "",
            args=command[1:],
            env=merged_env,
        )
        self._transport_ctx = stdio_client(server_params)
        read, write = await asyncio.wait_for(
            self._transport_ctx.__aenter__(),
            timeout=self.connect_timeout_seconds,
        )
        return await self._init_session(read, write)

    async def _connect_sse(self) -> bool:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = _substitute_vars(self.url, self.env)
        headers = _substitute_vars_in_dict(self.headers, self.env)
        self._transport_ctx = sse_client(url=url, headers=headers)
        read, write = await asyncio.wait_for(
            self._transport_ctx.__aenter__(),
            timeout=self.connect_timeout_seconds,
        )
        return await self._init_session(read, write)

    async def _connect_http(self) -> bool:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = _substitute_vars(self.url, self.env)
        headers = _substitute_vars_in_dict(self.headers, self.env)
        self._transport_ctx = streamablehttp_client(url=url, headers=headers)
        # streamablehttp_client returns (read, write, get_session_fn) — 3-tuple
        result = await asyncio.wait_for(
            self._transport_ctx.__aenter__(),
            timeout=self.connect_timeout_seconds,
        )
        read, write = result[0], result[1]
        return await self._init_session(read, write)

    async def _init_session(self, read, write) -> bool:
        from mcp import ClientSession

        self._session = ClientSession(read, write)
        await asyncio.wait_for(
            self._session.__aenter__(), timeout=self.connect_timeout_seconds
        )
        await asyncio.wait_for(
            self._session.initialize(), timeout=self.connect_timeout_seconds
        )
        await self._load_tools_and_resources()
        self._connected = True
        return True

    async def _load_tools_and_resources(self) -> None:
        tools_result = await asyncio.wait_for(
            self._session.list_tools(),
            timeout=self.connect_timeout_seconds,
        )
        self._tools = [
            McpTool(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
                server_name=self.name,
            )
            for t in tools_result.tools
        ]
        try:
            resources_result = await asyncio.wait_for(
                self._session.list_resources(),
                timeout=self.connect_timeout_seconds,
            )
            self._resources = [
                McpResource(
                    uri=str(r.uri),
                    name=r.name or str(r.uri),
                    description=r.description or "",
                    mime_type=r.mimeType or "text/plain",
                    server_name=self.name,
                )
                for r in (resources_result.resources or [])
            ]
        except Exception:
            self._resources = []

    async def disconnect(self) -> None:
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._transport_ctx:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None
        self._connected = False

    async def list_tools(self) -> list[McpTool]:
        return list(self._tools)

    async def list_resources(self) -> list[McpResource]:
        return list(self._resources)

    async def read_resource(self, uri: str) -> str:
        if not self._session or not self._connected:
            return "Error: not connected to MCP server"
        try:
            result = await asyncio.wait_for(
                self._session.read_resource(uri),
                timeout=self.call_timeout_seconds,
            )
            texts: list[str] = []
            for item in getattr(result, "contents", []):
                if hasattr(item, "text"):
                    texts.append(item.text)
                elif hasattr(item, "blob"):
                    texts.append(f"[binary blob: {len(item.blob)} bytes]")
            output = "\n".join(texts)
            if len(output) > self.max_output_chars:
                return output[: self.max_output_chars] + "\n... [MCP resource truncated]"
            return output or "(empty resource)"
        except asyncio.TimeoutError:
            return f"Error reading MCP resource '{uri}': timed out"
        except Exception as exc:
            return f"Error reading MCP resource '{uri}': {exc}"

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        if not self._session or not self._connected:
            return "Error: not connected to MCP server"
        if not isinstance(arguments, dict):
            return "Error: MCP tool arguments must be an object"
        try:
            result: Any = None
            last_exc: Exception | None = None
            for _attempt in range(self.retry_count + 1):
                try:
                    result = await asyncio.wait_for(
                        self._session.call_tool(tool_name, arguments),
                        timeout=self.call_timeout_seconds,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    await asyncio.sleep(0.05)
            if last_exc is not None:
                raise last_exc

            if hasattr(result, "content"):
                texts = [
                    item.text
                    for item in result.content
                    if hasattr(item, "text")
                ]
                output = "\n".join(texts)
            else:
                output = str(result)
            if len(output) > self.max_output_chars:
                return output[: self.max_output_chars] + "\n... [MCP output truncated]"
            return output
        except asyncio.TimeoutError:
            return (
                f"Error calling MCP tool '{tool_name}' on server '{self.name}': "
                f"timed out after {int(self.call_timeout_seconds * 1000)}ms"
            )
        except Exception as exc:
            return f"Error calling MCP tool '{tool_name}' on server '{self.name}': {exc}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self) -> "McpServerConnection":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()
