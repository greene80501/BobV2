from __future__ import annotations

import uuid
from typing import Any

REQUEST_USER_INPUT_DESCRIPTION = (
    "Request information or clarification from the user. "
    "Use when you need input that cannot be inferred from the codebase or context. "
    "Prefer specific, closed-ended questions when possible."
)

REQUEST_USER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "The question or request to show the user.",
        },
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["text", "boolean", "select"],
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "label"],
            },
            "description": "Optional structured input fields for multi-part prompts.",
        },
    },
    "required": ["prompt"],
}


async def request_user_input_handler(tool_input: dict, context: Any) -> str:
    """
    Forward a user-input request to the session callback and return the response.

    *context* must expose:
      - ``context.on_request_user_input`` – async callable
        ``(request_id: str, prompt: str, fields: list) -> str | None``,
        or ``None`` in non-interactive modes.
    """
    prompt: str = tool_input.get("prompt", "")
    if not prompt:
        return "Error: prompt is required"

    fields: list = tool_input.get("fields", [])
    request_id = str(uuid.uuid4())

    callback = getattr(context, "on_request_user_input", None)
    if callback is None:
        return "(user input not available in this mode)"

    try:
        response = await callback(request_id, prompt, fields)
    except Exception as exc:
        return f"Error requesting user input: {exc}"

    return response if response is not None else "(no response)"
