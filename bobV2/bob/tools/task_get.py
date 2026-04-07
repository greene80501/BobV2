"""Task get tool for Bob V2."""
from __future__ import annotations

from typing import Any
from datetime import datetime

TASK_GET_DESCRIPTION = (
    "Get detailed information about a specific task, including all output logs."
)

TASK_GET_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task ID to retrieve",
        },
    },
    "required": ["task_id"],
}


async def task_get_handler(tool_input: dict, context: Any) -> str:
    """Get details of a specific task including outputs."""
    task_id = tool_input.get("task_id", "")
    if not task_id:
        return "Error: task_id is required"
    
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    try:
        task = task_db.get_task(task_id)
        if task is None:
            return f"Error: task {task_id} not found"
        
        outputs = task_db.get_outputs(task_id)
        
        # Format task details
        lines = []
        lines.append(f"Task: {task.get('title', '')}")
        lines.append(f"ID: {task_id}")
        lines.append(f"Status: {task.get('status', '?')}")
        lines.append(f"Priority: {task.get('priority', '?')}")
        
        if task.get('description'):
            lines.append(f"Description: {task['description']}")
        
        # Format timestamps
        created_at = task.get('created_at')
        if created_at:
            dt = datetime.fromtimestamp(created_at)
            lines.append(f"Created: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        completed_at = task.get('completed_at')
        if completed_at:
            dt = datetime.fromtimestamp(completed_at)
            lines.append(f"Completed: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Add outputs
        if outputs:
            lines.append("")
            lines.append(f"Output Log ({len(outputs)} entries):")
            for output in outputs:
                timestamp = output.get('timestamp', 0)
                dt = datetime.fromtimestamp(timestamp)
                text = output.get('output_text', '')
                lines.append(f"  [{dt.strftime('%H:%M:%S')}] {text}")
        else:
            lines.append("")
            lines.append("No output logs yet")
        
        return "\n".join(lines)
    except Exception as exc:
        return f"Error getting task: {exc}"
