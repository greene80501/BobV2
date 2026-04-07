"""Task output tool for Bob V2."""
from __future__ import annotations

from typing import Any

TASK_OUTPUT_DESCRIPTION = (
    "Append an output log entry to a task. "
    "Use this to record progress, results, or notes about the task."
)

TASK_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task ID to append output to",
        },
        "output": {
            "type": "string",
            "description": "The output text to append",
        },
    },
    "required": ["task_id", "output"],
}


async def task_output_handler(tool_input: dict, context: Any) -> str:
    """Append output log to a task."""
    task_id = tool_input.get("task_id", "")
    if not task_id:
        return "Error: task_id is required"
    
    output = tool_input.get("output", "")
    if not output:
        return "Error: output is required"
    
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    try:
        # Verify task exists
        task = task_db.get_task(task_id)
        if task is None:
            return f"Error: task {task_id} not found"
        
        success = task_db.append_output(task_id, output)
        if success:
            return f"✓ Appended output to task {task_id}"
        else:
            return f"Error: failed to append output to task {task_id}"
    except Exception as exc:
        return f"Error appending output: {exc}"
