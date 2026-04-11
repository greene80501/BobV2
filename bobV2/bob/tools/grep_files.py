from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

GREP_FILES_DESCRIPTION = (
    "Search files for lines matching a regular expression. "
    "Returns results in filepath:lineno:line format, capped at max_results lines."
)

GREP_FILES_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "string",
            "description": "Regular expression pattern to search for.",
        },
        "path": {
            "type": "string",
            "description": "Root directory to search from (default: cwd).",
        },
        "file_pattern": {
            "type": "string",
            "description": "Glob filter for files to search, e.g. '*.py' (default: all files).",
        },
        "case_insensitive": {
            "type": "boolean",
            "description": "Perform case-insensitive matching (default: false).",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of matching lines to return (default: 200).",
        },
    },
    "required": ["pattern"],
}


async def grep_files_handler(tool_input: dict, context: Any) -> str:
    pattern_str: str = tool_input.get("pattern", "")
    if not pattern_str:
        return "Error: pattern is required"

    root_str: str | None = tool_input.get("path")
    if root_str:
        root = resolve_tool_path(root_str, context.cwd)
    else:
        root = context.cwd

    if not root.exists():
        return f"Error: directory not found: {root}"

    file_pattern: str = tool_input.get("file_pattern", "**/*")
    case_insensitive: bool = tool_input.get("case_insensitive", False)
    max_results: int = tool_input.get("max_results", 200)

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern_str, flags)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"

    results: list[str] = []
    truncated = False

    try:
        files = sorted(p for p in root.glob(file_pattern) if p.is_file())
    except Exception as exc:
        return f"Error: {exc}"

    for file_path in files:
        if truncated:
            break
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel = str(file_path.relative_to(root) if file_path.is_relative_to(root) else file_path)
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                results.append(f"{rel}:{lineno}:{line}")
                if len(results) >= max_results:
                    truncated = True
                    break

    if not results:
        return f"No matches for '{pattern_str}'"

    output = "\n".join(results)
    if truncated:
        output += f"\n[...truncated at {max_results} results]"
    return output
