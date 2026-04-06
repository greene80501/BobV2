from __future__ import annotations

from typing import Any

CLOSE_AGENT_DESCRIPTION = (
    "Shut down a sub-agent and release its resources. "
    "Call this when you no longer need the agent, whether it has finished or not."
)

CLOSE_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "ID of the sub-agent to close.",
        },
        "reason": {
            "type": "string",
            "description": "Optional human-readable reason for closing (logged).",
        },
    },
    "required": ["agent_id"],
}


async def close_agent_handler(tool_input: dict, context: Any) -> str:
    """
    Close and clean up a sub-agent.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_id: str = tool_input.get("agent_id", "")
    if not agent_id:
        return "Error: agent_id is required"

    reason: str = tool_input.get("reason", "")

    try:
        await thread_manager.close_agent(agent_id=agent_id, reason=reason or None)
        msg = f"Agent {agent_id} closed."
        if reason:
            msg += f" Reason: {reason}"
        return msg
    except KeyError:
        return f"Error: no sub-agent found with id '{agent_id}'"
    except Exception as exc:
        return f"Error closing agent {agent_id}: {exc}"
