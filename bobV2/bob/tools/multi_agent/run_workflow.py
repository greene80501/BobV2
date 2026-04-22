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
                },
                "required": ["id", "role", "task"],
            },
        },
        "mode": {
            "type": "string",
            "description": "Collaboration mode for the workflow (default: default).",
            "enum": ["default", "planner", "implementer", "reviewer", "verifier"],
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
    for n in nodes_raw:
        nodes.append(
            WorkflowNode(
                id=str(n.get("id", "")),
                role=str(n.get("role", "default")),
                task=str(n.get("task", "")),
                deps=[str(d) for d in n.get("deps", [])],
            )
        )

    mode = str(tool_input.get("mode", "default"))

    try:
        result = await supervisor.run_workflow(session=session, nodes=nodes, mode=mode)
        lines = [f"Workflow completed (mode={mode}):"]
        for node in result.get("nodes", []):
            status = node.get("status", "unknown")
            agent_id = node.get("agent_id", "?")
            role = node.get("role", "?")
            result_preview = (node.get("result") or "")[:200]
            lines.append(
                f"  [{node.get('id')}] role={role} status={status} agent={agent_id}"
            )
            if result_preview:
                lines.append(f"    result: {result_preview}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error running workflow: {exc}"
