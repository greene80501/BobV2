from __future__ import annotations

import json
from typing import Any

LIST_AGENTS_DESCRIPTION = (
    "List all sub-agents with their current status, what they're doing, "
    "and their resource usage. Use this to monitor parallel work and decide "
    "when to call wait_agent or assign_task."
)

LIST_AGENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "include_completed": {
            "type": "boolean",
            "description": "Include finished agents in the list. Default: true.",
        },
    },
}


async def list_agents_handler(tool_input: dict, context: Any) -> str:
    include_completed: bool = tool_input.get("include_completed", True)

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    agents = await agent_control.list_agents()

    if not include_completed:
        agents = [a for a in agents if a["status"] not in ("completed", "errored", "shutdown")]

    if not agents:
        return "No agents found."

    return json.dumps(agents, indent=2, ensure_ascii=False)
