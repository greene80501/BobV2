from __future__ import annotations

from typing import Any

LIST_AGENTS_DESCRIPTION = (
    "List all currently active sub-agents and their status. "
    "Use this to track running agents and their assigned tasks."
)

LIST_AGENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "include_completed": {
            "type": "boolean",
            "description": (
                "Whether to include recently completed agents in the listing "
                "(default: false)."
            ),
        },
    },
}


async def list_agents_handler(tool_input: dict, context: Any) -> str:
    """
    Return a formatted list of sub-agents managed by the thread manager.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    include_completed: bool = tool_input.get("include_completed", False)

    try:
        agents = thread_manager.list_agents(
            include_completed=include_completed
        )
    except Exception as exc:
        return f"Error listing agents: {exc}"

    if not agents:
        return "No active sub-agents."

    lines: list[str] = []
    for agent in agents:
        # Accept both dict and object-like agent descriptors
        if isinstance(agent, dict):
            agent_id = agent.get("id", "?")
            status = agent.get("status", "unknown")
            task = agent.get("task", "")
            path = agent.get("path", "?")
            depth = agent.get("depth", "?")
            queued = agent.get("queued_tasks", 0)
            parent_id = agent.get("parent_id")
            result_preview = agent.get("result_preview")
        else:
            agent_id = getattr(agent, "id", "?")
            status = getattr(agent, "status", "unknown")
            task = getattr(agent, "task", "")
            path = getattr(agent, "path", "?")
            depth = getattr(agent, "depth", "?")
            queued = getattr(agent, "queued_tasks", 0)
            parent_id = getattr(agent, "parent_id", None)
            result_preview = getattr(agent, "result_preview", None)

        task_preview = (task[:60] + "...") if len(task) > 60 else task
        parent_note = f" parent={parent_id}" if parent_id else ""
        result_note = f" result={result_preview}" if result_preview else ""
        lines.append(
            f"[{agent_id}] status={status} path={path} depth={depth} queued={queued}{parent_note}\n"
            f"  task={task_preview}{result_note}"
        )

    return "\n".join(lines)
