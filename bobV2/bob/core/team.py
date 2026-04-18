from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Team:
    name: str
    description: str
    instructions: str
    member_ids: list[str] = field(default_factory=list)


class TeamManager:
    """Manages named teams of agents that share a common instruction context."""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._teams: dict[str, Team] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_team(self, name: str, description: str, instructions: str) -> Team:
        if name in self._teams:
            raise ValueError(f"Team '{name}' already exists")
        team = Team(name=name, description=description, instructions=instructions)
        self._teams[name] = team
        return team

    def get_team(self, name: str) -> Optional[Team]:
        return self._teams.get(name)

    def list_teams(self) -> list[Team]:
        return list(self._teams.values())

    def delete_team(self, name: str) -> bool:
        if name not in self._teams:
            return False
        del self._teams[name]
        return True

    # ------------------------------------------------------------------
    # Agent spawning
    # ------------------------------------------------------------------

    async def spawn_team_agent(self, team_name: str, task: str) -> str:
        """Spawn an agent with the team's shared instructions prepended to its task."""
        team = self._teams.get(team_name)
        if team is None:
            raise ValueError(f"Team '{team_name}' not found")
        full_task = (
            f"[Team: {team_name}]\n"
            f"[Shared team instructions]:\n{team.instructions}\n\n"
            f"{task}"
        )
        tm = self._session.ensure_thread_manager()
        agent_id = await tm.spawn(task=full_task)
        team.member_ids.append(agent_id)
        return agent_id
