from __future__ import annotations

from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

GLOB_FILES_DESCRIPTION = (
    "Find files matching a glob pattern. "
    "Returns a newline-delimited list of matching paths (capped at 1,000)."
)

GLOB_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'.",
        },
        "path": {
            "type": "string",
            "description": "Root directory to search from (default: cwd).",
        },
    },
    "required": ["pattern"],
}

MAX_RESULTS = 1_000


async def glob_files_handler(tool_input: dict, context: Any) -> str:
    pattern: str = tool_input.get("pattern", "")
    if not pattern:
        return "Error: pattern is required"

    root_str: str | None = tool_input.get("path")
    if root_str:
        root = resolve_tool_path(root_str, context.cwd)
    else:
        root = context.cwd

    if not root.exists():
        return f"Error: directory not found: {root}"

    try:
        matches = list(root.glob(pattern))
    except Exception as exc:
        return f"Error: {exc}"

    # Sort for determinism; files only (skip dirs for cleaner output)
    matches = sorted(p for p in matches if p.is_file())

    truncated = len(matches) > MAX_RESULTS
    if truncated:
        matches = matches[:MAX_RESULTS]

    if not matches:
        return f"No files matching '{pattern}' in {root}"

    lines = [str(p.relative_to(root) if p.is_relative_to(root) else p) for p in matches]
    result = "\n".join(lines)
    if truncated:
        result += f"\n[...truncated at {MAX_RESULTS} results]"
    return result
