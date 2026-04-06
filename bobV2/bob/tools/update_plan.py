from __future__ import annotations

from typing import Any

from bob.protocol.plan_types import UpdatePlanArgs, PlanItemArg
from bob.protocol.config_types import StepStatus

UPDATE_PLAN_DESCRIPTION = (
    "Update the task plan checklist displayed to the user. "
    "Call this to create a plan at the start of complex tasks, and to mark "
    "steps as in_progress or completed as you work. "
    "Only use for multi-step tasks where a plan adds clarity."
)

UPDATE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "Brief explanation of what changed in the plan (optional).",
        },
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {
                        "type": "string",
                        "description": "Step description (concise, 5-8 words).",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                    },
                },
                "required": ["step", "status"],
            },
        },
    },
    "required": ["plan"],
}


async def update_plan_handler(tool_input: dict, context: Any) -> str:
    """
    Parse the plan update and forward it to the session callback.

    *context* must expose:
      - ``context.on_plan_update`` – async callable accepting an
        :class:`~bob.protocol.plan_types.UpdatePlanArgs`, or ``None``.
    """
    try:
        args = UpdatePlanArgs(**tool_input)
    except Exception as exc:
        return f"Error: invalid plan update arguments: {exc}"

    if context.on_plan_update is not None:
        await context.on_plan_update(args)

    completed = sum(1 for item in args.plan if item.status == StepStatus.COMPLETED)
    total = len(args.plan)
    return f"Plan updated. ({completed}/{total} steps completed)"
