from __future__ import annotations

import json
from typing import Any

SPAWN_AGENT_DESCRIPTION = (
    "Spawn a sub-agent to work on a task in parallel. The agent gets its own session "
    "and an isolated git worktree copy (if in a git repo). Returns an agent_id "
    "immediately — the agent runs in the background. Use wait_agent to collect results "
    "or list_agents to check status. Sub-agents run in full-auto mode and cannot "
    "spawn further agents."
)

SPAWN_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "The task or question for the sub-agent to work on.",
        },
        "name": {
            "type": "string",
            "description": (
                "Short descriptive name for this agent (e.g. 'researcher', 'planner', "
                "'code_analyzer'). Used in status display. Lowercase letters, numbers, underscores."
            ),
        },
        "model": {
            "type": "string",
            "description": (
                "Model override for this agent. Defaults to the current session model."
            ),
        },
        "fork_mode": {
            "type": "string",
            "enum": ["none", "all", "last_n:5", "last_n:10", "last_n:20"],
            "description": (
                "How much context to inherit from the parent conversation. "
                "'none' = fresh context (default), "
                "'all' = full conversation history, "
                "'last_n:N' = only the last N turns."
            ),
        },
    },
    "required": ["task"],
}


async def spawn_agent_handler(tool_input: dict, context: Any) -> str:
    task: str = (tool_input.get("task") or "").strip()
    if not task:
        return "Error: 'task' is required and cannot be empty."

    name: str | None = tool_input.get("name") or None
    model: str | None = tool_input.get("model") or None
    fork_mode: str = tool_input.get("fork_mode") or "none"

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    try:
        record = await agent_control.spawn(
            task,
            name=name,
            model=model,
            fork_mode=fork_mode,
        )
        return json.dumps({
            "agent_id": record.agent_id,
            "path": str(record.path),
            "name": record.path.name,
            "status": record.status.value,
            "message": (
                f"Agent '{record.path.name}' spawned (id: {record.agent_id}). "
                "Use wait_agent to collect the result."
            ),
        })
    except RuntimeError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error spawning agent: {exc}"
