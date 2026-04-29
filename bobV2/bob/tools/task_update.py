"""Task update tool for Bob V2."""
from __future__ import annotations

import asyncio
from typing import Any

TASK_UPDATE_DESCRIPTION = (
    "Update a task's status, title, description, or priority. "
    "Use this to mark tasks as in_progress, completed, or cancelled."
)

TASK_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task ID to update",
        },
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "cancelled"],
            "description": "New status for the task",
        },
        "title": {
            "type": "string",
            "description": "New title for the task",
        },
        "description": {
            "type": "string",
            "description": "New description for the task",
        },
        "priority": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "New priority for the task",
        },
    },
    "required": ["task_id"],
}


async def task_update_handler(tool_input: dict, context: Any) -> str:
    """Update an existing task."""
    task_id = tool_input.get("task_id", "")
    if not task_id:
        return "Error: task_id is required"
    
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    # Build update kwargs
    updates = {}
    if "status" in tool_input:
        from bob.core.task_db import TaskStatus
        updates["status"] = TaskStatus(tool_input["status"])
    if "title" in tool_input:
        updates["title"] = tool_input["title"]
    if "description" in tool_input:
        updates["description"] = tool_input["description"]
    if "priority" in tool_input:
        from bob.core.task_db import TaskPriority
        updates["priority"] = TaskPriority(tool_input["priority"])
    
    if not updates:
        return "Error: at least one field to update is required"
    
    try:
        task = task_db.update_task(task_id, **updates)
        if task is None:
            return f"Error: task {task_id} not found"

        status = task.get("status", "unknown")
        title = task.get("title", "")

        if status == "completed":
            session = getattr(context, "_session", None)
            if session is not None:
                from bob.protocol.config_types import HookEventName
                asyncio.create_task(session.hook_runner.run_hooks(
                    HookEventName.TASK_COMPLETED,
                    {"task_id": task_id, "title": title, "status": status},
                ))

        return f"✓ Updated task {task_id}: {title} (status: {status})"
    except Exception as exc:
        return f"Error updating task: {exc}"
