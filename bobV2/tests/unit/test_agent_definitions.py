from __future__ import annotations

from pathlib import Path

from bob.core.agents.control import derive_agent_name
from bob.core.agents.definitions import AgentDefinitionRegistry
from bob.core.agents.runtime import AgentIsolationMode, AgentPermissionMode


def test_definition_registry_exposes_builtin_agent_types(tmp_path: Path) -> None:
    registry = AgentDefinitionRegistry(tmp_path / "home", tmp_path / "repo")

    names = {definition.name for definition in registry.list_all()}

    assert "worker" in names
    assert "researcher" in names
    assert "planner" not in names
    assert "implementer" not in names
    assert "reviewer" not in names


def test_definition_registry_prefers_repo_over_user_scope(tmp_path: Path) -> None:
    bob_home = tmp_path / "home"
    repo = tmp_path / "repo"
    user_dir = bob_home / "agents"
    repo_dir = repo / ".bob" / "agents"
    user_dir.mkdir(parents=True)
    repo_dir.mkdir(parents=True)

    (user_dir / "researcher.toml").write_text(
        "\n".join(
            [
                'name = "researcher"',
                'description = "user researcher"',
                'isolation_mode = "shared_workspace"',
                'permission_mode = "read_only"',
            ]
        ),
        encoding="utf-8",
    )
    (repo_dir / "researcher.toml").write_text(
        "\n".join(
            [
                'name = "researcher"',
                'description = "repo researcher"',
                'isolation_mode = "git_worktree"',
                'permission_mode = "full_auto"',
            ]
        ),
        encoding="utf-8",
    )

    registry = AgentDefinitionRegistry(bob_home, repo)
    definition = registry.find("researcher")

    assert definition is not None
    assert definition.description == "repo researcher"
    assert definition.source == "repo"
    assert definition.isolation_mode == AgentIsolationMode.GIT_WORKTREE
    assert definition.permission_mode == AgentPermissionMode.FULL_AUTO


def test_definition_registry_loads_instructions_from_agent_markdown(tmp_path: Path) -> None:
    bob_home = tmp_path / "home"
    repo = tmp_path / "repo"
    agent_dir = repo / ".bob" / "agents" / "security"
    agent_dir.mkdir(parents=True)
    (agent_dir / "agent.toml").write_text(
        "\n".join(
            [
                'name = "security_custom"',
                'description = "custom security reviewer"',
            ]
        ),
        encoding="utf-8",
    )
    (agent_dir / "agent.md").write_text("Review the auth and sandbox changes.", encoding="utf-8")

    registry = AgentDefinitionRegistry(bob_home, repo)
    definition = registry.find("security_custom")

    assert definition is not None
    assert definition.instructions == "Review the auth and sandbox changes."


def test_definition_registry_unknown_builtin_falls_back_to_worker_shape(tmp_path: Path) -> None:
    registry = AgentDefinitionRegistry(tmp_path / "home", tmp_path / "repo")

    worker = registry.find("worker")
    unknown = registry.find("planner")

    assert worker is not None
    assert unknown is None


def test_derive_agent_name_uses_task_words() -> None:
    assert (
        derive_agent_name("Inspect the session lifecycle and report risk areas.")
        == "inspect_session_lifecycle_report"
    )
