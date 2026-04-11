from __future__ import annotations

from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

READ_FILE_DESCRIPTION = (
    "Read the contents of a file. Supports partial reads via start_line/end_line. "
    "Lines are 1-indexed and inclusive. Output is capped at 10,000 lines."
)

READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to read (relative to cwd or absolute).",
        },
        "start_line": {
            "type": "integer",
            "description": "First line to return (1-indexed, inclusive). Default: 1.",
        },
        "end_line": {
            "type": "integer",
            "description": "Last line to return (1-indexed, inclusive). Default: end of file.",
        },
        "encoding": {
            "type": "string",
            "description": "File encoding (default: utf-8).",
        },
    },
    "required": ["path"],
}

MAX_LINES = 10_000


async def read_file_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    if not path_str:
        return "Error: path is required"

    encoding: str = tool_input.get("encoding", "utf-8")

    p = resolve_tool_path(path_str, context.cwd)

    if not p.exists():
        return f"Error: file not found: {p}"
    if not p.is_file():
        return f"Error: not a file: {p}"

    try:
        text = p.read_text(encoding=encoding, errors="replace")
    except Exception as exc:
        return f"Error reading {p}: {exc}"

    lines = text.splitlines(keepends=True)
    total = len(lines)

    start: int = tool_input.get("start_line", 1)
    end: int = tool_input.get("end_line", total)

    # Clamp to valid range (1-indexed)
    start = max(1, start)
    end = min(total, end)

    if start > total:
        return f"(file has {total} lines; start_line {start} is out of range)"

    slice_ = lines[start - 1 : end]

    truncated = False
    if len(slice_) > MAX_LINES:
        slice_ = slice_[:MAX_LINES]
        truncated = True

    result = "".join(slice_)
    if truncated:
        result += f"\n[...truncated: showing lines {start}–{start + MAX_LINES - 1} of {total}]"
    elif start != 1 or end != total:
        result += f"\n[lines {start}–{end} of {total}]"

    return result
