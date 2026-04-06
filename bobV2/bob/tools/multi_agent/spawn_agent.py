from __future__ import annotations

from typing import Any

SPAWN_AGENT_DESCRIPTION = (
    "Spawn a sub-agent to handle a specific subtask independently. "
    "The sub-agent runs in its own context and returns its result when complete. "
    "Use for parallelisable work or tasks that benefit from a clean context."
)

SPAWN_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "Full task description for the sub-agent.",
        },
        "model": {
            "type": "string",
            "description": "Model override for the sub-agent (optional).",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory for the sub-agent (optional; defaults to parent cwd).",
        },
    },
    "required": ["task"],
}


async def spawn_agent_handler(tool_input: dict, context: Any) -> str:
    """
    Spawn a sub-agent.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    task: str = tool_input.get("task", "")
    if not task:
        return "Error: task description is required"

    model: str | None = tool_input.get("model")
    cwd: str | None = tool_input.get("cwd")

    try:
        agent_id = await thread_manager.spawn(task=task, model=model, cwd=cwd)
        return f"Sub-agent spawned (id={agent_id}) for task: {task[:120]}"
    except Exception as exc:
        return f"Error spawning sub-agent: {exc}"
