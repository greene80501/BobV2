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
        "template": {
            "type": "string",
            "description": "Agent template to use: explore, plan, verify, write, or review (optional).",
            "enum": ["explore", "plan", "verify", "write", "review"],
        },
        "name": {
            "type": "string",
            "description": (
                "Stable name for this agent role (e.g. 'explorer', 'reviewer'). "
                "When provided, the agent's findings are saved and injected into "
                "future spawns with the same name, giving it persistent memory."
            ),
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
    template: str | None = tool_input.get("template")
    name: str | None = tool_input.get("name")

    try:
        agent_id = await thread_manager.spawn(task=task, model=model, cwd=cwd, template=template, name=name)
        tmpl_note = f" [template={template}]" if template else ""
        name_note = f" [name={name}]" if name else ""
        return f"Sub-agent spawned (id={agent_id}){tmpl_note}{name_note} for task: {task[:120]}"
    except Exception as exc:
        return f"Error spawning sub-agent: {exc}"
