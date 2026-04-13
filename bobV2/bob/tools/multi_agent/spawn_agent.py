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
        "task_name": {
            "type": "string",
            "description": "Optional stable label for the initial task.",
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
        "parent_agent_ref": {
            "type": "string",
            "description": "Optional parent agent reference (id/path/name) to build tree edges.",
        },
        "parent_agent_id": {
            "type": "string",
            "description": "Backward-compatible alias for parent_agent_ref.",
        },
        "role": {
            "type": "string",
            "description": "Optional agent role label for metadata and filtering.",
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
    task_name: str | None = tool_input.get("task_name")
    name: str | None = tool_input.get("name")
    parent_agent_id: str | None = tool_input.get("parent_agent_ref") or tool_input.get("parent_agent_id")
    role: str | None = tool_input.get("role")
    allow_mutating_tools = True
    allowed_tools: list[str] | None = None
    if template:
        from bob.core.agent_templates import get_template

        tmpl = get_template(template)
        if tmpl and tmpl.allowed_tools:
            allowed_tools = sorted(tmpl.allowed_tools)
        if template in {"explore", "plan", "verify", "review"}:
            allow_mutating_tools = False

    try:
        agent_id = await thread_manager.spawn(
            task=task,
            model=model,
            cwd=cwd,
            template=template,
            task_name=task_name,
            name=name,
            parent_agent_id=parent_agent_id,
            role=role,
            allowed_tools=allowed_tools,
            allow_mutating_tools=allow_mutating_tools,
        )
        tmpl_note = f" [template={template}]" if template else ""
        name_note = f" [name={name}]" if name else ""
        parent_note = f" [parent={parent_agent_id}]" if parent_agent_id else ""
        role_note = f" [role={role}]" if role else ""
        task_note = f" [task_name={task_name}]" if task_name else ""
        return (
            f"Sub-agent spawned (id={agent_id}){tmpl_note}{task_note}{name_note}{parent_note}{role_note} "
            f"for task: {task[:120]}"
        )
    except Exception as exc:
        return f"Error spawning sub-agent: {exc}"
