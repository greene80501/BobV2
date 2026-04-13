from __future__ import annotations

from typing import Any

ASSIGN_TASK_DESCRIPTION = (
    "Assign a named task to an existing sub-agent. "
    "This replaces/updates the agent's primary task queue entry, unlike send_message."
)

ASSIGN_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_ref": {
            "type": "string",
            "description": "Agent reference (id, path, or unique name).",
        },
        "agent_id": {
            "type": "string",
            "description": "Backward-compatible alias for agent_ref.",
        },
        "task": {
            "type": "string",
            "description": "New task description to assign.",
        },
        "task_name": {
            "type": "string",
            "description": "Optional stable task name/label for tracking and wait snapshots.",
        },
        "interrupt_running": {
            "type": "boolean",
            "description": "If true, interrupt the currently running task before assigning this one.",
        },
        "clear_queue": {
            "type": "boolean",
            "description": "If true, drop any queued tasks before assigning this one.",
        },
    },
    "required": ["task"],
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

    agent_ref: str = (tool_input.get("agent_ref") or tool_input.get("agent_id") or "").strip()
    task: str = tool_input.get("task", "")
    task_name: str | None = tool_input.get("task_name")

    if not agent_ref:
        return "Error: agent_ref (or agent_id) is required"
    if not task:
        return "Error: task description is required"
    interrupt_running = bool(tool_input.get("interrupt_running", False))
    clear_queue = bool(tool_input.get("clear_queue", False))

    try:
        snap = await thread_manager.assign_task(
            agent_id=agent_ref,
            task=task,
            task_name=task_name,
            interrupt_running=interrupt_running,
            clear_queue=clear_queue,
        )
        label = f" task_name={task_name}" if task_name else ""
        return (
            f"Task assigned to agent {snap.get('id')} ({snap.get('path')}){label}: {task[:120]}\n"
            f"status={snap.get('status')} queued_tasks={snap.get('queued_tasks')}"
        )
    except KeyError:
        return f"Error: no sub-agent found with reference '{agent_ref}'"
    except Exception as exc:
        return f"Error assigning task to agent {agent_ref}: {exc}"
