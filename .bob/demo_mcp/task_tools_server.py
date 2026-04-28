from __future__ import annotations

import json


async def main() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server("task_tools")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo_task",
                description="Normalize a task title and optional details.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "details": {"type": "string"},
                    },
                    "required": ["title"],
                },
            ),
            Tool(
                name="make_checklist",
                description="Turn a goal and step list into a markdown checklist.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["goal", "items"],
                },
            ),
            Tool(
                name="status_summary",
                description="Summarize open, blocked, and completed work items.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "open_items": {"type": "array", "items": {"type": "string"}},
                        "blocked_items": {"type": "array", "items": {"type": "string"}},
                        "completed_items": {"type": "array", "items": {"type": "string"}},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        arguments = arguments or {}
        if name == "echo_task":
            title = str(arguments["title"]).strip()
            details = str(arguments.get("details", "")).strip()
            parts = [f"Task: {title}"]
            if details:
                parts.append(f"Details: {details}")
            return [TextContent(type="text", text="\n".join(parts))]

        if name == "make_checklist":
            goal = str(arguments["goal"]).strip()
            items = [str(item).strip() for item in arguments.get("items", []) if str(item).strip()]
            lines = [f"Goal: {goal}"]
            lines.extend(f"- [ ] {item}" for item in items)
            return [TextContent(type="text", text="\n".join(lines))]

        if name == "status_summary":
            open_items = [str(item).strip() for item in arguments.get("open_items", []) if str(item).strip()]
            blocked_items = [str(item).strip() for item in arguments.get("blocked_items", []) if str(item).strip()]
            completed_items = [str(item).strip() for item in arguments.get("completed_items", []) if str(item).strip()]
            lines = [
                f"Open: {len(open_items)}",
                f"Blocked: {len(blocked_items)}",
                f"Completed: {len(completed_items)}",
            ]
            if open_items:
                lines.append("Open items:")
                lines.extend(f"- {item}" for item in open_items)
            if blocked_items:
                lines.append("Blocked items:")
                lines.extend(f"- {item}" for item in blocked_items)
            if completed_items:
                lines.append("Completed items:")
                lines.extend(f"- {item}" for item in completed_items)
            return [TextContent(type="text", text="\n".join(lines))]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
