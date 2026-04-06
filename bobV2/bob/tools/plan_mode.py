from __future__ import annotations

from typing import Any

ENTER_PLAN_MODE_DESCRIPTION = (
    "Switch to Plan mode. In Plan mode only read-only tools are available — "
    "no file writes, no shell commands that modify state. "
    "Use this to safely explore and plan before making changes."
)

ENTER_PLAN_MODE_SCHEMA: dict = {
    "type": "object",
    "properties": {},
}

EXIT_PLAN_MODE_DESCRIPTION = (
    "Exit Plan mode and restore full tool access."
)

EXIT_PLAN_MODE_SCHEMA: dict = {
    "type": "object",
    "properties": {},
}


async def enter_plan_mode_handler(tool_input: dict, context: Any) -> str:
    session = getattr(context, "_session", None)
    if session is None:
        # Try via parent chain
        session = getattr(context, "session", None)
    if session is not None:
        session._plan_mode = True
    return "Plan mode enabled. Only read-only tools are now available."


async def exit_plan_mode_handler(tool_input: dict, context: Any) -> str:
    session = getattr(context, "_session", None)
    if session is None:
        session = getattr(context, "session", None)
    if session is not None:
        session._plan_mode = False
    return "Plan mode disabled. Full tool access restored."
