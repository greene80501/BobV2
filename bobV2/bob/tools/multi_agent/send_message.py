from __future__ import annotations

from typing import Any

SEND_MESSAGE_DESCRIPTION = (
    "Send a message to a running sub-agent. "
    "Use this to provide additional instructions or context after spawning."
)

SEND_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "ID of the target sub-agent (returned by spawn_agent).",
        },
        "message": {
            "type": "string",
            "description": "Message content to deliver to the sub-agent.",
        },
    },
    "required": ["agent_id", "message"],
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

    agent_id: str = tool_input.get("agent_id", "")
    message: str = tool_input.get("message", "")

    if not agent_id:
        return "Error: agent_id is required"
    if not message:
        return "Error: message is required"

    try:
        await thread_manager.send_message(agent_id=agent_id, message=message)
        return f"Message sent to agent {agent_id}."
    except KeyError:
        return f"Error: no sub-agent found with id '{agent_id}'"
    except Exception as exc:
        return f"Error sending message to agent {agent_id}: {exc}"
