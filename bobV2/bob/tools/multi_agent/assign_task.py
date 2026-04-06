from __future__ import annotations

from typing import Any

ASSIGN_TASK_DESCRIPTION = (
    "Assign a new task to an existing idle sub-agent. "
    "Prefer this over spawning a new agent when one is already available, "
    "to reduce overhead."
)

ASSIGN_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "ID of the target sub-agent.",
        },
        "task": {
            "type": "string",
            "description": "New task description to assign.",
        },
    },
    "required": ["agent_id", "task"],
}


async def assign_task_handler(tool_input: dict, context: Any) -> str:
    """
    Assign a new task to an existing sub-agent.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_id: str = tool_input.get("agent_id", "")
    task: str = tool_input.get("task", "")

    if not agent_id:
        return "Error: agent_id is required"
    if not task:
        return "Error: task description is required"

    try:
        await thread_manager.assign_task(agent_id=agent_id, task=task)
        return f"Task assigned to agent {agent_id}: {task[:120]}"
    except KeyError:
        return f"Error: no sub-agent found with id '{agent_id}'"
    except Exception as exc:
        return f"Error assigning task to agent {agent_id}: {exc}"
