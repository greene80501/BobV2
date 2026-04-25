from __future__ import annotations

from typing import Any

RUN_WORKFLOW_DESCRIPTION = (
    "Run a structured multi-agent workflow. "
    "Provide a list of workflow nodes (each with an id, role, task, and optional dependencies). "
    "The supervisor spawns agents for ready nodes and waits for dependencies before launching downstream work. "
    "Roles: 'implementer' (writes code), 'reviewer' (reviews code), 'verifier' (runs tests/checks), 'default' (general task). "
    "Use this when you have a multi-step task with clear dependencies and want parallel execution where possible."
)

RUN_WORKFLOW_SCHEMA = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "description": "List of workflow nodes to execute.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Unique node identifier.",
                    },
                    "role": {
                        "type": "string",
                        "description": "Agent role for this node: implementer, reviewer, verifier, or default.",
                        "enum": ["implementer", "reviewer", "verifier", "default"],
                    },
                    "task": {
                        "type": "string",
                        "description": "Task description for the agent.",
                    },
                    "deps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of node ids that must complete before this node starts.",
                    },
                    "required_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tools that must be available for this node to run.",
                    },
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit tool allowlist for this node.",
                    },
                    "read_only": {
                        "type": "boolean",
                        "description": "When true, mutating tools are blocked for this node.",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Optional wall-clock timeout for this node.",
                    },
                },
                "required": ["id", "role", "task"],
            },
        },
        "mode": {
            "type": "string",
            "description": "Collaboration mode for the workflow (default: default).",
            "enum": ["default", "planner", "implementer", "reviewer", "verifier"],
        },
        "require_real_agents": {
            "type": "boolean",
            "description": "When true, fail instead of degrading to a trivial workflow.",
        },
    },
    "required": ["nodes"],
}


async def run_workflow_handler(tool_input: dict, context: Any) -> str:
    """
    Run a multi-agent workflow via the AgentSupervisor.

    *context* must expose:
      - ``context._session`` – BobSession instance.
    """
    session = getattr(context, "_session", None)
    if session is None:
        return "Error: no session available"

    nodes_raw = tool_input.get("nodes", [])
    if not nodes_raw:
        return "Error: nodes list is required"

    from bob.core.agents import AgentSupervisor, WorkflowNode
    from bob.core.agents.manager import AgentManager

    manager = AgentManager()
    supervisor = AgentSupervisor(manager)

    nodes: list[WorkflowNode] = []
    require_real_agents = bool(tool_input.get("require_real_agents", False))
    available_tools = set(session.tool_registry.list_tools())
    errors: list[str] = []
    for n in nodes_raw:
        node_id = str(n.get("id", ""))
        task = str(n.get("task", ""))
        role = str(n.get("role", "default"))
        required_tools = sorted({str(t) for t in n.get("required_tools", []) if str(t).strip()})
        allowed_tools = [str(t) for t in n.get("allowed_tools", []) if str(t).strip()]
        read_only = bool(n.get("read_only", False))
        timeout_seconds = n.get("timeout_seconds")
        missing_tools = [tool for tool in required_tools if tool not in available_tools]
        if missing_tools:
            errors.append(
                f"Node '{node_id}' requires unavailable tools: {', '.join(missing_tools)}"
            )
        resolved_timeout: float | None = None
        if timeout_seconds is not None:
            try:
                resolved_timeout = float(timeout_seconds)
            except (TypeError, ValueError):
                errors.append(f"Node '{node_id}' has invalid timeout_seconds: {timeout_seconds!r}")
        if read_only and allowed_tools:
            disallowed = []
            for tool_name in allowed_tools:
                caps = session.tool_registry.get_tool_capabilities(tool_name)
                if tool_name == "shell":
                    continue
                if caps.is_mutating:
                    disallowed.append(tool_name)
            if disallowed:
                errors.append(
                    f"Node '{node_id}' is read-only but allows mutating tools: {', '.join(disallowed)}"
                )
        nodes.append(
            WorkflowNode(
                id=node_id,
                role=role,
                task=task,
                deps=[str(d) for d in n.get("deps", [])],
                required_tools=required_tools,
                allowed_tools=allowed_tools or None,
                read_only=read_only,
                timeout_seconds=resolved_timeout,
            )
        )

    mode = str(tool_input.get("mode", "default"))
    if require_real_agents and len(nodes) < 2:
        errors.append("Workflow requested real multi-agent execution but fewer than 2 nodes were provided")
    if errors:
        return "Workflow blocked:\n" + "\n".join(f"  - {msg}" for msg in errors)

    try:
        result = await supervisor.run_workflow(session=session, nodes=nodes, mode=mode)
        lines = [f"Workflow completed (mode={mode}):"]
        failed = 0
        for node in result.get("nodes", []):
            status = node.get("status", "unknown")
            agent_id = node.get("agent_id", "?")
            role = node.get("role", "?")
            result_preview = (node.get("result") or "")[:200]
            lines.append(
                f"  [{node.get('id')}] role={role} status={status} agent={agent_id}"
            )
            error = node.get("error") or ""
            if status not in {"completed"}:
                failed += 1
            if error:
                lines.append(f"    error: {error[:200]}")
            if result_preview:
                lines.append(f"    result: {result_preview}")
        if failed:
            lines.insert(1, f"Result: partial failure ({failed} node(s) not completed)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error running workflow: {exc}"
