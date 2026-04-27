from __future__ import annotations

from pathlib import Path
from typing import Any
from bob.tools.path_utils import resolve_tool_path

LIST_DIR_DESCRIPTION = "List the contents of a directory."

LIST_DIR_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Directory path to list "
                "(relative to cwd or absolute; default: current working directory)."
            ),
        },
    },
}

# Directories to skip during listing (common noise)
_SKIP_NAMES = {".git", "__pycache__", "node_modules", ".tox", ".mypy_cache"}


async def list_dir_handler(tool_input: dict, context: Any) -> str:
    """
    List the entries of a directory, with directories annotated by a trailing
    slash.  Hidden entries (names starting with ".") are included but
    common noise directories are filtered unless the user asks specifically
    for one.

    *context* must expose:
      - ``context.cwd`` – :class:`pathlib.Path`
    """
    path_str: str = tool_input.get("path", ".")
    path = resolve_tool_path(path_str, context.cwd)

    if not path.exists():
        return f"Error: directory not found: {path}"
    if not path.is_dir():
        return f"Error: not a directory: {path}"

    try:
        all_entries = list(path.iterdir())
    except PermissionError:
        return f"Error: permission denied: {path}"

    dirs: list[str] = []
    files: list[str] = []

    for entry in all_entries:
        name = entry.name
        is_link = entry.is_symlink()
        try:
            is_dir = entry.is_dir() if is_link else entry.is_dir()
        except OSError:
            is_dir = False

        if is_dir and not is_link:
            # Annotate with "/" and mark skippable noise dirs
            if name in _SKIP_NAMES:
                dirs.append(f"{name}/ (skipped)")
            else:
                dirs.append(f"{name}/")
        elif is_link:
            try:
                target = entry.resolve()
                target_is_dir = target.is_dir()
            except OSError:
                target = Path("<unresolved>")
                target_is_dir = False
            if target_is_dir:
                dirs.append(f"{name}@ -> {target}")
            else:
                files.append(f"{name}@ -> {target}")
        else:
            files.append(name)

    dirs.sort(key=str.lower)
    files.sort(key=str.lower)
    entries = dirs + files

    if not entries:
        return "(empty)"

    return "\n".join(entries)
