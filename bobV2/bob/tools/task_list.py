"""Task list tool for Bob V2."""
from __future__ import annotations

from typing import Any

TASK_LIST_DESCRIPTION = (
    "List all tasks, optionally filtered by status. "
    "Shows task_id, title, status, priority, and creation time."
)

TASK_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "completed", "cancelled"],
            "description": "Filter tasks by status (optional)",
        },
    },
}


async def task_list_handler(tool_input: dict, context: Any) -> str:
    """List all tasks, optionally filtered by status."""
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    status_filter = None
    if "status" in tool_input:
        from bob.core.task_db import TaskStatus
        try:
            status_filter = TaskStatus(tool_input["status"])
        except ValueError:
            return f"Error: invalid status '{tool_input['status']}'"
    
    try:
        tasks = task_db.list_tasks(status=status_filter)
        
        if not tasks:
            if status_filter:
                return f"No tasks with status '{status_filter.value}'"
            return "No tasks found"
        
        # Format as table
        lines = []
        lines.append("Tasks:")
        lines.append("")
        
        for task in tasks:
            task_id = task.get("task_id", "?")
            title = task.get("title", "")
            status = task.get("status", "?")
            priority = task.get("priority", "?")
            
            # Format: [ID] Title (status, priority)
            lines.append(f"  [{task_id}] {title}")
            lines.append(f"    Status: {status} | Priority: {priority}")
        
        lines.append("")
        lines.append(f"Total: {len(tasks)} task(s)")
        
        return "\n".join(lines)
    except Exception as exc:
        return f"Error listing tasks: {exc}"
