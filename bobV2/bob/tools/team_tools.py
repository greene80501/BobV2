from __future__ import annotations

from typing import Any

TEAM_CREATE_DESCRIPTION = (
    "Create a named team of agents that share a common set of instructions. "
    "All agents spawned into this team will have the team's instructions "
    "prepended to their task context. "
    "Use teams when you need multiple agents with the same specialised role "
    "(e.g., a 'frontend-team' that always uses React hooks, or a 'test-team' "
    "that enforces pytest fixtures)."
)

TEAM_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Unique team name (e.g. 'frontend-team').",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of the team's purpose.",
        },
        "instructions": {
            "type": "string",
            "description": "Shared instructions injected into every agent spawned on this team.",
        },
    },
    "required": ["name", "instructions"],
}

TEAM_SPAWN_AGENT_DESCRIPTION = (
    "Spawn a new agent as a member of an existing team. The team's shared "
    "instructions are automatically prepended to the agent's task. "
    "Use this to create multiple parallel workers with the same baseline context."
)

TEAM_SPAWN_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "team_name": {
            "type": "string",
            "description": "Name of the team to spawn the agent into.",
        },
        "task": {
            "type": "string",
            "description": "Task description for the agent.",
        },
    },
    "required": ["team_name", "task"],
}

TEAM_LIST_DESCRIPTION = "List all active teams and their member agent IDs."

TEAM_LIST_SCHEMA = {
    "type": "object",
    "properties": {},
}

TEAM_DELETE_DESCRIPTION = "Delete a team by name."

TEAM_DELETE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "Name of the team to delete.",
        },
    },
    "required": ["name"],
}


def _get_team_manager(context: Any):
    session = getattr(context, "_session", None)
    if session is None:
        return None
    return session.ensure_team_manager()


async def team_create_handler(tool_input: dict, context: Any) -> str:
    tm = _get_team_manager(context)
    if tm is None:
        return "Error: no session available"
    name: str = tool_input.get("name", "").strip()
    description: str = tool_input.get("description", "").strip()
    instructions: str = tool_input.get("instructions", "").strip()
    if not name:
        return "Error: name is required"
    if not instructions:
        return "Error: instructions is required"
    try:
        team = tm.create_team(name, description, instructions)
        return f"Team '{team.name}' created."
    except ValueError as exc:
        return f"Error: {exc}"


async def team_spawn_agent_handler(tool_input: dict, context: Any) -> str:
    tm = _get_team_manager(context)
    if tm is None:
        return "Error: no session available"
    team_name: str = tool_input.get("team_name", "").strip()
    task: str = tool_input.get("task", "").strip()
    if not team_name:
        return "Error: team_name is required"
    if not task:
        return "Error: task is required"
    try:
        agent_id = await tm.spawn_team_agent(team_name, task)
        return f"Agent {agent_id} spawned into team '{team_name}'."
    except (ValueError, Exception) as exc:
        return f"Error: {exc}"


async def team_list_handler(tool_input: dict, context: Any) -> str:
    tm = _get_team_manager(context)
    if tm is None:
        return "Error: no session available"
    teams = tm.list_teams()
    if not teams:
        return "No teams defined."
    lines = []
    for t in teams:
        members = ", ".join(t.member_ids) if t.member_ids else "(no members yet)"
        lines.append(f"  {t.name}: {t.description or '(no description)'}")
        lines.append(f"    members: {members}")
    return "\n".join(lines)


async def team_delete_handler(tool_input: dict, context: Any) -> str:
    tm = _get_team_manager(context)
    if tm is None:
        return "Error: no session available"
    name: str = tool_input.get("name", "").strip()
    if not name:
        return "Error: name is required"
    if tm.delete_team(name):
        return f"Team '{name}' deleted."
    return f"Error: team '{name}' not found."
