"""Task creation tool for Bob V2."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

TASK_CREATE_DESCRIPTION = (
    "Create a new task with title, description, and priority. "
    "Returns the task_id for future reference."
)

TASK_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Brief title for the task",
        },
        "description": {
            "type": "string",
            "description": "Detailed description of what needs to be done",
        },
        "priority": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Task priority level",
        },
    },
    "required": ["title"],
}


async def task_create_handler(tool_input: dict, context: Any) -> str:
    """Create a new task in the task database."""
    title = tool_input.get("title", "")
    if not title:
        return "Error: title is required"
    
    description = tool_input.get("description", "")
    priority = tool_input.get("priority", "medium")
    
    # Generate unique task ID
    task_id = str(uuid.uuid4())[:8]
    
    # Get task_db from context
    task_db = getattr(context, "task_db", None)
    if task_db is None:
        return "Error: task database not available"
    
    try:
        from bob.core.task_db import TaskPriority, TaskStatus
        
        task = task_db.create_task(
            task_id=task_id,
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            priority=TaskPriority(priority),
        )

        session = getattr(context, "_session", None)
        if session is not None:
            from bob.protocol.config_types import HookEventName
            asyncio.create_task(session.hook_runner.run_hooks(
                HookEventName.TASK_CREATED,
                {"task_id": task_id, "title": title, "priority": priority},
            ))

        return f"✓ Created task {task_id}: {title} (priority: {priority})"
    except Exception as exc:
        return f"Error creating task: {exc}"
