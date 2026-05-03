from __future__ import annotations

import json
from typing import Any

WAIT_AGENT_DESCRIPTION = (
    "Wait for one or more sub-agents to complete and return their results. "
    "Blocks until all specified agents finish (or the timeout is hit). "
    "Pass multiple agent IDs to wait for all of them at once. "
    "Results include the agent's final output, status, tool use count, and token count."
)

WAIT_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "List of agent IDs (from spawn_agents/spawn_agent) or agent names to wait for. "
                "At least one required."
            ),
            "minItems": 1,
        },
        "timeout_ms": {
            "type": "integer",
            "description": (
                "Maximum time to wait in milliseconds. Default: 300000 (5 minutes). "
                "If timeout is hit, returns partial results with timed-out agents showing "
                "their current status."
            ),
            "minimum": 1000,
            "maximum": 1800000,
        },
    },
    "required": ["agent_ids"],
}


async def wait_agent_handler(tool_input: dict, context: Any) -> str:
    agent_ids: list[str] = tool_input.get("agent_ids") or []
    timeout_ms: int = int(tool_input.get("timeout_ms") or 300_000)

    if not agent_ids:
        return "Error: 'agent_ids' must be a non-empty list."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    results = await agent_control.wait_for(agent_ids, timeout_ms=timeout_ms)
    return json.dumps(results, indent=2, ensure_ascii=False)
