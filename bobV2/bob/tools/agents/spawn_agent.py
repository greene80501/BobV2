from __future__ import annotations

import json
from typing import Any


SPAWN_AGENTS_DESCRIPTION = (
    "Spawn multiple background workers in parallel for genuinely independent tracks of work. "
    "Use this only after decomposing the task. Do not use it for single-worker delegation. "
    "Each worker should own a clear scope, and the caller should wait for all workers before "
    "synthesizing the final result."
)

_AGENT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "The exact prompt for this worker's independent task.",
        },
        "name": {
            "type": "string",
            "description": "Optional short name for this worker. If omitted, Bob derives one from the task.",
        },
        "agent_type": {
            "type": "string",
            "description": "Optional preset. Built-in options are worker (default) and researcher.",
        },
        "model": {
            "type": "string",
            "description": "Optional model override for this worker.",
        },
        "fork_mode": {
            "type": "string",
            "enum": ["none", "all", "last_n:5", "last_n:10", "last_n:20"],
            "description": "How much context this worker should inherit from the parent thread.",
        },
        "isolation_mode": {
            "type": "string",
            "enum": ["shared_workspace", "git_worktree"],
            "description": "Workspace isolation mode for this worker.",
        },
        "permission_mode": {
            "type": "string",
            "enum": ["full_auto", "read_only"],
            "description": "Runtime permission mode for this worker.",
        },
    },
    "required": ["task"],
}

SPAWN_AGENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "agents": {
            "type": "array",
            "items": _AGENT_ITEM_SCHEMA,
            "minItems": 2,
            "description": (
                "The independent workers to spawn in parallel. Provide at least two. "
                "Use task prompts to define whether each worker should research, plan, implement, or review."
            ),
        },
    },
    "required": ["agents"],
}


SPAWN_AGENT_DESCRIPTION = (
    "Spawn one background agent. This is primarily a compatibility/API path. For model-driven "
    "parallel work, prefer spawn_agents with at least two independent workers."
)

SPAWN_AGENT_SCHEMA = {
    "type": "object",
    "properties": dict(_AGENT_ITEM_SCHEMA["properties"]),
    "required": ["task"],
}


def _serialize_record(record) -> dict[str, Any]:
    return {
        "agent_id": record.agent_id,
        "path": str(record.path),
        "name": record.path.name,
        "agent_type": record.agent_type,
        "status": record.status.value,
        "cwd": record.cwd,
        "worktree_path": record.worktree_path,
        "isolation_mode": record.isolation_mode,
        "permission_mode": record.permission_mode,
    }


async def spawn_agents_handler(tool_input: dict, context: Any) -> str:
    raw_agents = tool_input.get("agents") or []
    if not isinstance(raw_agents, list) or len(raw_agents) < 2:
        return "Error: 'agents' must contain at least two independent worker tasks."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    spawned: list[dict[str, Any]] = []
    try:
        for item in raw_agents:
            if not isinstance(item, dict):
                return "Error: each item in 'agents' must be an object."
            task = (item.get("task") or "").strip()
            if not task:
                return "Error: every spawned worker requires a non-empty 'task'."
            record = await agent_control.spawn(
                task,
                name=item.get("name") or None,
                agent_type=item.get("agent_type") or None,
                model=item.get("model") or None,
                fork_mode=item.get("fork_mode") or "none",
                isolation_mode=item.get("isolation_mode") or None,
                permission_mode=item.get("permission_mode") or None,
            )
            spawned.append(_serialize_record(record))
    except RuntimeError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error spawning agents: {exc}"

    return json.dumps(
        {
            "agents": spawned,
            "message": (
                f"Spawned {len(spawned)} workers. Use wait_agent with all returned agent_ids "
                "before synthesizing the final result."
            ),
        }
    )


async def spawn_agent_handler(tool_input: dict, context: Any) -> str:
    task: str = (tool_input.get("task") or "").strip()
    if not task:
        return "Error: 'task' is required and cannot be empty."

    agent_control = getattr(getattr(context, "_session", None), "agent_control", None)
    if agent_control is None:
        return "Error: agent system not available in this session."

    try:
        record = await agent_control.spawn(
            task,
            name=tool_input.get("name") or None,
            agent_type=tool_input.get("agent_type") or None,
            model=tool_input.get("model") or None,
            fork_mode=tool_input.get("fork_mode") or "none",
            isolation_mode=tool_input.get("isolation_mode") or None,
            permission_mode=tool_input.get("permission_mode") or None,
        )
    except RuntimeError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error spawning agent: {exc}"

    payload = _serialize_record(record)
    payload["message"] = (
        f"Agent '{record.path.name}' spawned (id: {record.agent_id}). "
        "Use wait_agent to collect the result."
    )
    return json.dumps(payload)
