from __future__ import annotations

from pathlib import Path
from typing import Any

EDIT_FILE_DESCRIPTION = (
    "Edit a file by replacing an exact string with a new string. "
    "old_string must appear exactly once in the file. "
    "To create a new file, pass empty old_string and a path that does not exist."
)

EDIT_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to edit (relative to cwd or absolute).",
        },
        "old_string": {
            "type": "string",
            "description": "Exact text to find and replace. Empty string = create new file.",
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text.",
        },
    },
    "required": ["path", "old_string", "new_string"],
}


async def edit_file_handler(tool_input: dict, context: Any) -> str:
    path_str: str = tool_input.get("path", "")
    old_string: str = tool_input.get("old_string", "")
    new_string: str = tool_input.get("new_string", "")

    if not path_str:
        return "Error: path is required"

    p = Path(path_str)
    if not p.is_absolute():
        p = context.cwd / p

    # Create mode: empty old_string + file doesn't exist
    if old_string == "" and not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new_string, encoding="utf-8")
            return f"Created {p} ({len(new_string.encode()):,} bytes)"
        except Exception as exc:
            return f"Error creating {p}: {exc}"

    if not p.exists():
        return f"Error: file not found: {p}"
    if not p.is_file():
        return f"Error: not a file: {p}"

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Error reading {p}: {exc}"

    count = text.count(old_string)
    if count == 0:
        # Show a helpful excerpt from the file for context
        preview = text[:200].replace("\n", "↵")
        return (
            f"Error: old_string not found in {p}.\n"
            f"File starts with: {preview!r}"
        )
    if count > 1:
        return (
            f"Error: old_string appears {count} times in {p}. "
            "Provide more context to make the match unique."
        )

    new_text = text.replace(old_string, new_string, 1)
    try:
        p.write_text(new_text, encoding="utf-8")
    except Exception as exc:
        return f"Error writing {p}: {exc}"

    # Count lines changed
    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1
    return f"Edited {p}: replaced {old_lines} line(s) with {new_lines} line(s)"
