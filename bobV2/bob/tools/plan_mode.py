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
    "Exit Plan mode and present the plan for user approval. "
    "Provide a summary of the plan you've created."
)

EXIT_PLAN_MODE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "plan_summary": {
            "type": "string",
            "description": "A clear summary of the plan, including key steps and files to be modified.",
        },
    },
    "required": ["plan_summary"],
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
    if session is None:
        return "Error: session not available"
    
    plan_summary = tool_input.get("plan_summary", "")
    if not plan_summary:
        return "Error: plan_summary is required when exiting plan mode"
    
    # Store plan summary for approval
    session._pending_plan_summary = plan_summary
    
    # Emit approval request event
    from bob.protocol.events import PlanApprovalRequestedEvent
    await session._event_queue.put(
        PlanApprovalRequestedEvent(plan_summary=plan_summary)
    )
    
    # Wait for approval response
    # This will be handled by the TUI and responded via PlanApprovalOp
    return "Plan submitted for approval. Waiting for user response..."
