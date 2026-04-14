from __future__ import annotations

from typing import Any

WAIT_AGENT_DESCRIPTION = (
    "Wait for one or more sub-agents to reach target states. "
    "Supports waiting for any target or all targets with timeout control."
)

WAIT_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Single agent reference (id, path, or unique name).",
        },
        "agent_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Multiple agent references to wait on.",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum time to wait in milliseconds (default: 60000).",
        },
        "wait_for_states": {
            "type": "array",
            "items": {"type": "string"},
            "description": "States to consider done (default: idle/failed/closed).",
        },
        "any_target": {
            "type": "boolean",
            "description": "If true (default), return when any target reaches done state. If false, wait for all.",
        },
    },
    "required": [],
}

DEFAULT_WAIT_TIMEOUT_MS = 60_000


async def wait_agent_handler(tool_input: dict, context: Any) -> str:
    """
    Block until one or more sub-agents reach the requested state(s).

    *context* must expose:
      - ``context.thread_manager`` - thread manager instance, or ``None``.
    """
    thread_manager = getattr(context, "thread_manager", None)
    if thread_manager is None:
        return "Error: multi-agent not available in this session"

    agent_id: str = (tool_input.get("agent_id") or "").strip()
    agent_ids: list[str] = [str(x).strip() for x in (tool_input.get("agent_ids") or []) if str(x).strip()]
    if agent_id:
        agent_ids = [agent_id, *[x for x in agent_ids if x != agent_id]]
    if not agent_ids:
        return "Error: provide agent_id or agent_ids"

    raw_timeout = tool_input.get("timeout", DEFAULT_WAIT_TIMEOUT_MS)
    try:
        timeout_ms = int(raw_timeout)
    except (TypeError, ValueError):
        return "Error: timeout must be an integer number of milliseconds"
    if timeout_ms < 0:
        return "Error: timeout must be >= 0"

    timeout_s = timeout_ms / 1000.0
    any_target = bool(tool_input.get("any_target", True))
    wait_for_states_raw = tool_input.get("wait_for_states") or ["idle", "failed", "closed"]
    wait_for_states = {str(x).strip() for x in wait_for_states_raw if str(x).strip()}
    if not wait_for_states:
        wait_for_states = {"idle", "failed", "closed"}

    try:
        result = await thread_manager.wait_for_agents(
            agent_refs=agent_ids,
            timeout=timeout_s,
            wait_for_states=wait_for_states,
            any_target=any_target,
        )
        if result.get("timed_out"):
            return (
                f"Wait timed out after {timeout_ms}ms "
                f"(targets={', '.join(agent_ids)}, any_target={any_target})"
            )
        matched = result.get("matched_agent_id")
        agents = result.get("agents") or {}
        lines = [
            f"Wait completed. matched_agent_id={matched} any_target={any_target}",
            "Agent snapshots:",
        ]
        for aid, snap in agents.items():
            lines.append(
                f"- {aid}: status={snap.get('status')} path={snap.get('path')} "
                f"queued={snap.get('queued_tasks')} result={snap.get('result_preview')}"
            )
        return "\n".join(lines)
    except KeyError:
        return "Error: one or more agent references were not found"
    except Exception as exc:
        return f"Error waiting for agents: {exc}"
