from __future__ import annotations


async def run_as_mcp_server() -> None:
    """Run bob as an MCP server, exposing its built-in tools to MCP clients."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
    except ImportError:
        print("MCP SDK not available. Install with: pip install mcp")
        return

    server = Server("bob")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="shell",
                description=(
                    "Execute a shell command. Use for running programs, reading files, "
                    "searching, git operations, and all other terminal tasks."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command and arguments, e.g. ['ls', '-la']",
                        },
                        "workdir": {
                            "type": "string",
                            "description": "Optional working directory override.",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in milliseconds (default: 10000).",
                        },
                    },
                    "required": ["command"],
                },
            ),
            Tool(
                name="view_image",
                description="View an image file and return a description of its contents.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute or relative path to the image file.",
                        },
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="update_plan",
                description="Update the current plan with new steps or status.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of plan step descriptions.",
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Explanation of the plan update.",
                        },
                    },
                    "required": ["steps"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Dispatch tool calls. In server mode we run without a full BobSession."""
        import os
        from pathlib import Path

        if name == "shell":
            from bob.core.exec import execute_command
            from bob.sandbox.base import NoSandbox
            from bob.protocol.config_types import SandboxPolicy, SandboxMode

            command: list[str] = arguments.get("command", [])
            if not command:
                return [TextContent(type="text", text="Error: empty command")]

            workdir = arguments.get("workdir")
            cwd = Path(workdir).resolve() if workdir else Path.cwd()
            timeout_ms: int = arguments.get("timeout", 10_000)

            sandbox = NoSandbox()
            result = await execute_command(
                command=command,
                cwd=cwd,
                sandbox=sandbox,
                timeout_ms=timeout_ms,
            )
            output = result.aggregated_output or result.stdout
            if result.timed_out:
                output = f"[Timed out after {timeout_ms}ms]\n{output}"
            elif result.exit_code != 0:
                output = f"{output}\n[Exit code: {result.exit_code}]"
            return [TextContent(type="text", text=output)]

        elif name == "view_image":
            path_str = arguments.get("path", "")
            if not path_str:
                return [TextContent(type="text", text="Error: no path provided")]
            return [TextContent(type="text", text=f"[Image viewing not available in server mode: {path_str}]")]

        elif name == "update_plan":
            steps = arguments.get("steps", [])
            explanation = arguments.get("explanation", "")
            text = "Plan updated"
            if explanation:
                text += f": {explanation}"
            if steps:
                text += "\nSteps:\n" + "\n".join(f"  - {s}" for s in steps)
            return [TextContent(type="text", text=text)]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
