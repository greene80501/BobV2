from __future__ import annotations
import asyncio
from typing import Optional
from bob.mcp.client import McpResource, McpServerConnection, McpTool


class McpManager:
    """Manages all configured MCP server connections for a bob session."""

    def __init__(self, mcp_server_configs: dict):
        """
        Parameters
        ----------
        mcp_server_configs:
            Dict mapping server name -> config.  Each config may be a dict
            with "command" and optional "env" keys, or a McpServerConfig
            pydantic object (from bob.config.schema).
        """
        self._configs = mcp_server_configs
        self._connections: dict[str, McpServerConnection] = {}
        self._all_tools: list[McpTool] = []
        self._all_resources: list[McpResource] = []
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> dict[str, bool]:
        """Connect to all configured servers concurrently.

        Returns a dict mapping server name -> True/False (connected or not).
        """
        if not self._configs:
            self._started = True
            return {}

        async def _connect_one(name: str, config) -> tuple[str, bool]:
            def _get(key: str, default):
                if isinstance(config, dict):
                    return config.get(key, default)
                return getattr(config, key, default)

            transport = _get("type", "stdio")
            env = dict(_get("env", {}))
            connect_timeout_seconds = float(_get("connect_timeout_seconds", 15.0))
            call_timeout_seconds = float(_get("call_timeout_seconds", 30.0))
            retry_count = int(_get("retry_count", 1))
            max_output_chars = int(_get("max_output_chars", 32000))

            if transport == "stdio":
                raw_cmd = _get("command", [])
                raw_args = _get("args", [])
                command = list(raw_cmd) + list(raw_args)
                url = ""
                headers: dict = {}
            else:
                command = []
                url = _get("url", "")
                headers = dict(_get("headers", {}))

            conn = McpServerConnection(
                name=name,
                command=command,
                env=env,
                transport=transport,
                url=url,
                headers=headers,
                connect_timeout_seconds=connect_timeout_seconds,
                call_timeout_seconds=call_timeout_seconds,
                retry_count=retry_count,
                max_output_chars=max_output_chars,
            )
            success = await conn.connect()
            self._connections[name] = conn
            if success:
                tools = await conn.list_tools()
                self._all_tools.extend(tools)
                resources = await conn.list_resources()
                self._all_resources.extend(resources)
            return name, success

        tasks = [
            asyncio.create_task(_connect_one(name, cfg))
            for name, cfg in self._configs.items()
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, bool] = {}
        for outcome in raw_results:
            if isinstance(outcome, Exception):
                continue
            name, ok = outcome
            results[name] = ok

        self._started = True
        return results

    async def stop(self) -> None:
        """Disconnect all active server connections."""
        tasks = [
            asyncio.create_task(conn.disconnect())
            for conn in self._connections.values()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()
        self._all_tools.clear()
        self._all_resources.clear()
        self._started = False

    # ------------------------------------------------------------------
    # Tool access
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[McpTool]:
        """Return all tools discovered across all connected servers."""
        return list(self._all_tools)

    def get_all_resources(self) -> list[McpResource]:
        """Return all resources discovered across all connected servers."""
        return list(self._all_resources)

    async def read_resource(self, server_name: str, uri: str) -> str:
        conn = self._connections.get(server_name)
        if not conn:
            return f"Error: MCP server '{server_name}' not found or not connected"
        if not conn.is_connected:
            return f"Error: MCP server '{server_name}' is disconnected"
        return await conn.read_resource(uri)

    def get_tool_specs(self) -> list[dict]:
        """Return tool specs in OpenAI function-calling format.

        Tool names are prefixed with ``<server_name>__`` to avoid collisions
        across servers.
        """
        specs: list[dict] = []
        for tool in self._all_tools:
            prefixed_name = f"{tool.server_name}__{tool.name}"
            specs.append({
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": f"[{tool.server_name}] {tool.description}",
                    "parameters": tool.input_schema,
                }
            })
        return specs

    async def call_tool(self, prefixed_name: str, arguments: dict) -> str:
        """Dispatch a tool call to the appropriate MCP server.

        Parameters
        ----------
        prefixed_name:
            Tool name in ``<server_name>__<tool_name>`` format, as returned
            by :meth:`get_tool_specs`.
        arguments:
            Tool arguments dict.
        """
        if "__" not in prefixed_name:
            return f"Error: invalid MCP tool name (expected 'server__tool'): {prefixed_name!r}"
        server_name, tool_name = prefixed_name.split("__", 1)
        if not server_name or not tool_name:
            return f"Error: invalid MCP tool name (expected 'server__tool'): {prefixed_name!r}"
        conn = self._connections.get(server_name)
        if not conn:
            return f"Error: MCP server '{server_name}' not found or not connected"
        if not conn.is_connected:
            return f"Error: MCP server '{server_name}' is disconnected"
        if not isinstance(arguments, dict):
            return "Error: MCP tool arguments must be an object"
        return await conn.call_tool(tool_name, arguments)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def connected_servers(self) -> list[str]:
        return [n for n, c in self._connections.items() if c.is_connected]

    def failed_servers(self) -> list[str]:
        return [n for n, c in self._connections.items() if not c.is_connected]

    @property
    def is_started(self) -> bool:
        return self._started
