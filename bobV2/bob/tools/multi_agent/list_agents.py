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
        agents = await thread_manager.list_agents(
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
        else:
            agent_id = getattr(agent, "id", "?")
            status = getattr(agent, "status", "unknown")
            task = getattr(agent, "task", "")

        task_preview = (task[:60] + "...") if len(task) > 60 else task
        lines.append(f"[{agent_id}] {status}: {task_preview}")

    return "\n".join(lines)
