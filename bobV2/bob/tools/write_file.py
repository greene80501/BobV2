from __future__ import annotations

from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

WRITE_FILE_DESCRIPTION = (
    "Write content to a file, creating parent directories as needed. "
    "Overwrites any existing file at the given path."
)

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to write (relative to cwd or absolute).",
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file.",
        },
        "encoding": {
            "type": "string",
            "description": "File encoding (default: utf-8).",
        },
    },
    "required": ["path", "content"],
}


async def write_file_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    content: str = tool_input.get("content", "")
    encoding: str = tool_input.get("encoding", "utf-8")

    if not path_str:
        return "Error: path is required"

    p = resolve_tool_path(path_str, context.cwd)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        byte_count = len(content.encode(encoding))
        return f"Wrote {byte_count:,} bytes to {p}"
    except Exception as exc:
        return f"Error writing {p}: {exc}"
