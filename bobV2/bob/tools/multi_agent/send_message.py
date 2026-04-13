from __future__ import annotations

from typing import Any

SEND_MESSAGE_DESCRIPTION = (
    "Send a contextual message to a sub-agent without replacing its primary task. "
    "Use assign_task when you want to schedule a new concrete task."
)

SEND_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_ref": {
            "type": "string",
            "description": "Target sub-agent reference (id, path, or unique name).",
        },
        "agent_id": {
            "type": "string",
            "description": "Backward-compatible alias for agent_ref.",
        },
        "message": {
            "type": "string",
            "description": "Message content to deliver to the sub-agent.",
        },
    },
    "required": ["message"],
}


async def send_message_handler(tool_input: dict, context: Any) -> str:
    """
    Send a message to a running sub-agent.

    *context* must expose:
      - ``context.thread_manager`` – thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_ref: str = (tool_input.get("agent_ref") or tool_input.get("agent_id") or "").strip()
    message: str = tool_input.get("message", "")

    if not agent_ref:
        return "Error: agent_ref (or agent_id) is required"
    if not message:
        return "Error: message is required"

    try:
        result = await thread_manager.send_message(agent_id=agent_ref, message=message)
        return result
    except KeyError:
        return f"Error: no sub-agent found with reference '{agent_ref}'"
    except Exception as exc:
        return f"Error sending message to agent {agent_ref}: {exc}"
