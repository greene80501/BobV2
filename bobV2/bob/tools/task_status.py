from __future__ import annotations

import json
from typing import Any


TASK_STATUS_DESCRIPTION = (
    "Inspect a delegated subagent task. Use this to poll, wait for completion, "
    "or retrieve the latest result and transcript tail for a child session."
)

TASK_STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task_id returned by task.",
        },
        "wait": {
            "type": "boolean",
            "description": "When true, block until the task finishes or timeout_ms elapses.",
        },
        "timeout_ms": {
            "type": "integer",
            "description": "Maximum wait time when wait=true. Default 300000.",
            "minimum": 1000,
            "maximum": 1800000,
        },
    },
    "required": ["task_id"],
}


async def task_status_handler(tool_input: dict, context: Any) -> str:
    task_id = (tool_input.get("task_id") or "").strip()
    wait = bool(tool_input.get("wait", False))
    timeout_ms = int(tool_input.get("timeout_ms") or 300_000)

    if not task_id:
        return "Error: 'task_id' is required."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    if wait:
        results = await agent_control.wait_for([task_id], timeout_ms=timeout_ms)
        payload = results.get(task_id)
        if payload is None and len(results) == 1:
            payload = next(iter(results.values()))
        return json.dumps(payload or {"task_id": task_id, "status": "not_found"}, indent=2, ensure_ascii=False)

    status = await agent_control.get_status(task_id)
    if status is None:
        return json.dumps({"task_id": task_id, "status": "not_found"}, indent=2, ensure_ascii=False)
    return json.dumps(status, indent=2, ensure_ascii=False)
