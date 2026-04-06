from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TODO_WRITE_DESCRIPTION = (
    "Manage a todo list stored in .bob-todos.json in the workspace root. "
    "Pass a list of todo items to create or update them. "
    "Each item requires: id (string), content (string), status (pending|in_progress|done), priority (high|medium|low)."
)

TODO_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "description": "List of todo items to create or update.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "content": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done"],
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["id", "content", "status", "priority"],
            },
        },
    },
    "required": ["todos"],
}

TODO_FILE = ".bob-todos.json"


async def todo_write_handler(tool_input: dict, context: Any) -> str:
    todos_input: list[dict] = tool_input.get("todos", [])
    if not isinstance(todos_input, list):
        return "Error: todos must be an array"

    todo_path = context.cwd / TODO_FILE

    # Load existing
    existing: dict[str, dict] = {}
    if todo_path.exists():
        try:
            existing = {t["id"]: t for t in json.loads(todo_path.read_text())}
        except Exception:
            existing = {}

    # Merge
    for item in todos_input:
        item_id = item.get("id")
        if not item_id:
            continue
        existing[item_id] = item

    # Write back
    all_todos = list(existing.values())
    try:
        todo_path.write_text(json.dumps(all_todos, indent=2))
    except Exception as exc:
        return f"Error writing {TODO_FILE}: {exc}"

    pending = sum(1 for t in all_todos if t.get("status") == "pending")
    in_progress = sum(1 for t in all_todos if t.get("status") == "in_progress")
    done = sum(1 for t in all_todos if t.get("status") == "done")

    return (
        f"Updated {TODO_FILE}: {len(all_todos)} total "
        f"({pending} pending, {in_progress} in_progress, {done} done)"
    )
