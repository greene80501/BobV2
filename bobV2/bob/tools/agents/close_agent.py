from __future__ import annotations

from typing import Any

CLOSE_AGENT_DESCRIPTION = (
    "Cancel and shut down a running sub-agent. The agent's worktree is cleaned up "
    "without merging any changes. Use this if an agent is going in the wrong direction "
    "or is no longer needed. Completed agents cannot be closed."
)

CLOSE_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "Agent ID or name to close.",
        },
    },
    "required": ["target"],
}


async def close_agent_handler(tool_input: dict, context: Any) -> str:
    target: str = (tool_input.get("target") or "").strip()
    if not target:
        return "Error: 'target' is required."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    prev_status = await agent_control.close(target)
    if prev_status is None:
        return f"Error: agent '{target}' not found."
    return f"Agent '{target}' closed (was: {prev_status})."
