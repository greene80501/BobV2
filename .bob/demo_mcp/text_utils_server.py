from __future__ import annotations

import json
import re


def _sentence_chunks(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()]


async def main() -> None:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    server = Server("text_utils")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="summarize_text",
                description="Return the first few sentences of a text block as a simple summary.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "max_sentences": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="extract_todos",
                description="Extract TODO, FIXME, and action-style bullet lines from text.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="word_stats",
                description="Return simple word, line, and character counts for text.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        arguments = arguments or {}
        text = str(arguments.get("text", ""))

        if name == "summarize_text":
            max_sentences = max(1, min(int(arguments.get("max_sentences", 3)), 8))
            summary = " ".join(_sentence_chunks(text)[:max_sentences])
            return [TextContent(type="text", text=summary or "(empty text)")]

        if name == "extract_todos":
            matches = []
            for line in text.splitlines():
                stripped = line.strip()
                upper = stripped.upper()
                if "TODO" in upper or "FIXME" in upper or stripped.startswith(("- [ ]", "* [ ]")):
                    matches.append(stripped)
            return [TextContent(type="text", text="\n".join(matches) or "(no todos found)")]

        if name == "word_stats":
            stats = {
                "lines": len(text.splitlines()),
                "words": len([word for word in re.split(r"\s+", text.strip()) if word]),
                "characters": len(text),
            }
            return [TextContent(type="text", text=json.dumps(stats, indent=2, sort_keys=True))]

        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
