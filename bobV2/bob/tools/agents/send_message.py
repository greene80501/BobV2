from __future__ import annotations

from typing import Any

SEND_MESSAGE_DESCRIPTION = (
    "Send a message to a running sub-agent without interrupting its current turn. "
    "The message will be delivered at the start of the agent's next turn. "
    "Use assign_task to send a message AND trigger a new turn immediately."
)

SEND_MESSAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "Agent ID or name to send the message to.",
        },
        "message": {
            "type": "string",
            "description": "The message content to send.",
        },
    },
    "required": ["target", "message"],
}


async def send_message_handler(tool_input: dict, context: Any) -> str:
    target: str = (tool_input.get("target") or "").strip()
    message: str = (tool_input.get("message") or "").strip()

    if not target:
        return "Error: 'target' is required."
    if not message:
        return "Error: 'message' is required."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    ok = await agent_control.send_message(target, message, trigger_turn=False)
    if ok:
        return f"Message queued for agent '{target}'. It will be delivered on the next turn."
    return f"Error: agent '{target}' not found."


ASSIGN_TASK_DESCRIPTION = (
    "Send a message to a running sub-agent AND trigger a new turn immediately. "
    "Use this to redirect an agent mid-run or provide urgent corrections. "
    "The agent will start processing your message right away."
)

ASSIGN_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "Agent ID or name to send the task to.",
        },
        "message": {
            "type": "string",
            "description": "Instructions or corrections to send to the agent.",
        },
    },
    "required": ["target", "message"],
}


async def assign_task_handler(tool_input: dict, context: Any) -> str:
    target: str = (tool_input.get("target") or "").strip()
    message: str = (tool_input.get("message") or "").strip()

    if not target:
        return "Error: 'target' is required."
    if not message:
        return "Error: 'message' is required."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    ok = await agent_control.send_message(target, message, trigger_turn=True)
    if ok:
        return f"Task assigned to '{target}' and agent triggered."
    return f"Error: agent '{target}' not found."
