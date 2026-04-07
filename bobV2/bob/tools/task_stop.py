"""Task stop/cancel tool for Bob V2."""
from __future__ import annotations

from typing import Any

TASK_STOP_DESCRIPTION = (
    "Cancel a running task. Sets the task status to 'cancelled'."
)

TASK_STOP_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task ID to cancel",
        },
    },
    "required": ["task_id"],
}


async def task_stop_handler(tool_input: dict, context: Any) -> str:
    """Cancel a task."""
    task_id = tool_input.get("task_id", "")
    if not task_id:
        return "Error: task_id is required"
    
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    try:
        task = task_db.cancel_task(task_id)
        if task is None:
            return f"Error: task {task_id} not found"
        
        title = task.get("title", "")
        return f"✓ Cancelled task {task_id}: {title}"
    except Exception as exc:
        return f"Error cancelling task: {exc}"
