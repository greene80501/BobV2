from __future__ import annotations

from typing import Any


TASK_DESCRIPTION = (
    "Launch or resume a subagent task backed by its own child session.\n\n"
    "When NOT to use the task tool:\n"
    "- If you want to read a specific file path, use read_file or glob_files instead.\n"
    "- If you are searching for a specific symbol or text pattern, use grep_files instead.\n"
    "- If you are searching within a specific file or a very small known set of files, use read_file instead.\n"
    "- If no available subagent is a good fit for the work, use other tools directly.\n\n"
    "Usage notes:\n"
    "1. Fresh delegation must launch at least 2 subagents in parallel; use a single response with multiple task tool calls.\n"
    "2. For broad two-project or two-system understanding/comparison work, issue exactly two fresh explore task calls in the same response, one per side.\n"
    "3. The task result is not visible to the user until you summarize it yourself. The output includes a task_id you can reuse later to continue the same child session.\n"
    "4. Each fresh child session starts with fresh context unless you provide task_id to resume it, so your prompt should contain a highly detailed task description and specify exactly what the subagent should return.\n"
    "5. Clearly tell the subagent whether it should write code or only do research, and tell it how to verify its work if possible.\n"
    "6. Use explore for codebase investigation and general for broader multi-step execution."
)

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short 3-5 word description of the task shown in the task UI.",
        },
        "prompt": {
            "type": "string",
            "description": "The exact task for the child subagent to perform.",
        },
        "subagent_type": {
            "type": "string",
            "description": "The type of specialized agent to use for this task. Prefer general or explore.",
        },
        "task_id": {
            "type": "string",
            "description": "Optional existing task_id to resume instead of starting a fresh child session.",
        },
        "background": {
            "type": "boolean",
            "description": "When true, start the task and return immediately.",
        },
        "model": {
            "type": "string",
            "description": "Optional model override for this child session.",
        },
        "isolation_mode": {
            "type": "string",
            "enum": ["shared_workspace", "git_worktree"],
            "description": "Optional Bob-specific isolation override for coding tasks.",
        },
    },
    "required": ["description", "prompt", "subagent_type"],
}


def _format_result(task_id: str, text: str) -> str:
    return "\n".join(
        [
            f"task_id: {task_id}",
            "",
            "<task_result>",
            text,
            "</task_result>",
        ]
    )


async def task_handler(tool_input: dict, context: Any) -> str:
    description = (tool_input.get("description") or "").strip()
    prompt = (tool_input.get("prompt") or "").strip()
    subagent_type = (tool_input.get("subagent_type") or "").strip()
    task_id = (tool_input.get("task_id") or "").strip() or None
    background = bool(tool_input.get("background", False))
    batch = getattr(context, "task_batch", None) or {}

    if not description:
        return "Error: 'description' is required."
    if not prompt:
        return "Error: 'prompt' is required."
    if not subagent_type:
        return "Error: 'subagent_type' is required."

    session = getattr(context, "_session", None)
    if getattr(session, "_plan_mode", False) and subagent_type != "explore":
        return "Error: Plan mode only allows the explore subagent type."

    agent_control = getattr(session, "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    try:
        record = await agent_control.start_task(
            prompt,
            description=description,
            subagent_type=subagent_type,
            task_id=task_id,
            model=tool_input.get("model") or None,
            isolation_mode=tool_input.get("isolation_mode") or None,
            background=background,
            group_id=batch.get("group_id"),
            group_size=int(batch.get("group_size") or 0),
            group_index=int(batch.get("group_index") or 0),
        )
    except Exception as exc:
        return f"Error: {exc}"

    if background:
        return _format_result(
            record.agent_id,
            "Background task started. Continue your current work and call task_status when you need the result.",
        )

    results = await agent_control.wait_for([record.agent_id], timeout_ms=1_800_000)
    result = results.get(record.agent_id) or {}
    status = result.get("status", "unknown")
    if status == "completed":
        return _format_result(record.agent_id, str(result.get("result") or "Task completed."))
    if status == "errored":
        return _format_result(record.agent_id, f"Task failed: {result.get('error') or 'unknown error'}")
    return _format_result(record.agent_id, f"Task state: {status}")
