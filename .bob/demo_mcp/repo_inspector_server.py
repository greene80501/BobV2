from __future__ import annotations

from pathlib import Path
import json


async def main() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server("repo_inspector")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_files",
                description="List repository files relative to the selected root.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "root": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                },
            ),
            Tool(
                name="read_file_head",
                description="Read the first N lines of a text file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "lines": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="find_in_files",
                description="Search for a literal text pattern across repository files.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "root": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                    },
                    "required": ["pattern"],
                },
            ),
        ]

    def _root_from(arguments: dict) -> Path:
        root = arguments.get("root") or "."
        return Path(root).resolve()

    def _iter_text_files(root: Path):
        ignored = {".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignored for part in path.parts):
                continue
            yield path

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        arguments = arguments or {}
        if name == "list_files":
            root = _root_from(arguments)
            limit = max(1, min(int(arguments.get("limit", 50)), 200))
            files = []
            for path in _iter_text_files(root):
                files.append(path.relative_to(root).as_posix())
                if len(files) >= limit:
                    break
            return [TextContent(type="text", text="\n".join(files) or "(no files found)")]

        if name == "read_file_head":
            file_path = Path(arguments["path"]).resolve()
            lines = max(1, min(int(arguments.get("lines", 40)), 200))
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            excerpt = "\n".join(text.splitlines()[:lines])
            return [TextContent(type="text", text=excerpt or "(empty file)")]

        if name == "find_in_files":
            root = _root_from(arguments)
            pattern = str(arguments["pattern"])
            limit = max(1, min(int(arguments.get("limit", 30)), 200))
            matches = []
            for path in _iter_text_files(root):
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if pattern in line:
                        matches.append(f"{path.relative_to(root).as_posix()}:{line_number}: {line.strip()}")
                        if len(matches) >= limit:
                            return [TextContent(type="text", text="\n".join(matches))]
            return [TextContent(type="text", text="\n".join(matches) or "(no matches found)")]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
