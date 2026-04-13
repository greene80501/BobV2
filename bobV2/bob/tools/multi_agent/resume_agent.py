from __future__ import annotations

from typing import Any

RESUME_AGENT_DESCRIPTION = (
    "Resume a previously closed or idle sub-agent. "
    "Optionally provide a task to enqueue immediately after resume."
)

RESUME_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Agent reference to resume (id, path, or unique name).",
        },
        "task": {
            "type": "string",
            "description": "Optional task to enqueue immediately after resume.",
        },
    },
    "required": ["agent_id"],
}


async def resume_agent_handler(tool_input: dict, context: Any) -> str:
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_id: str = (tool_input.get("agent_id") or "").strip()
    task: str | None = tool_input.get("task")
    if not agent_id:
        return "Error: agent_id is required"

    try:
        snap = await thread_manager.resume_agent(agent_id=agent_id, task=task)
        msg = (
            f"Agent resumed: id={snap.get('id')} path={snap.get('path')} "
            f"status={snap.get('status')} depth={snap.get('depth')}"
        )
        if task:
            msg += f"\nTask enqueued: {task[:120]}"
        return msg
    except KeyError:
        return f"Error: no sub-agent found with reference '{agent_id}'"
    except Exception as exc:
        return f"Error resuming agent {agent_id}: {exc}"

