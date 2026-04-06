from __future__ import annotations

from typing import Any

WAIT_AGENT_DESCRIPTION = (
    "Wait for a sub-agent to finish its current task and return its result. "
    "Blocks until the agent completes or the optional timeout is reached."
)

WAIT_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "ID of the sub-agent to wait for.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum time to wait in milliseconds (default: 60000).",
        },
    },
    "required": ["agent_id"],
}

DEFAULT_WAIT_TIMEOUT_MS = 60_000


async def wait_agent_handler(tool_input: dict, context: Any) -> str:
    """
    Block until a sub-agent completes and return its output.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_id: str = tool_input.get("agent_id", "")
    if not agent_id:
        return "Error: agent_id is required"

    timeout_ms: int = tool_input.get("timeout", DEFAULT_WAIT_TIMEOUT_MS)
    timeout_s = timeout_ms / 1000.0

    try:
        result = await thread_manager.wait_for_agent(
            agent_id=agent_id, timeout=timeout_s
        )
        if result is None:
            return f"Agent {agent_id} timed out after {timeout_ms}ms"
        return f"Agent {agent_id} completed:\n{result}"
    except KeyError:
        return f"Error: no sub-agent found with id '{agent_id}'"
    except Exception as exc:
        return f"Error waiting for agent {agent_id}: {exc}"
