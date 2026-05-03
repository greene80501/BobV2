from __future__ import annotations

from pathlib import Path
from typing import Optional

from bob.core.agents.runtime import (
    AgentDefinition,
    AgentIsolationMode,
    AgentPermissionMode,
)


def _read_toml(path: Path) -> dict:
    import tomllib

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return data if isinstance(data, dict) else {}


def _load_definition_from_toml(path: Path, *, source: str) -> Optional[AgentDefinition]:
    if not path.exists():
        return None
    try:
        data = _read_toml(path)
    except Exception:
        return None

    name = str(data.get("name") or path.stem).strip()
    if not name:
        return None

    instructions = str(data.get("instructions") or "")
    instructions_file = str(data.get("instructions_file") or "").strip()
    if instructions_file:
        candidate = (path.parent / instructions_file).resolve()
        try:
            instructions = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    else:
        for candidate in (path.with_suffix(".md"), path.parent / "agent.md"):
            if candidate.exists():
                try:
                    instructions = candidate.read_text(encoding="utf-8").strip()
                    break
                except OSError:
                    pass

    try:
        return AgentDefinition(
            name=name,
            description=str(data.get("description") or ""),
            instructions=instructions,
            model=(str(data.get("model")).strip() if data.get("model") else None),
            allowed_tools=[
                str(tool).strip()
                for tool in (data.get("allowed_tools") or [])
                if str(tool).strip()
            ],
            fork_mode=str(data.get("fork_mode") or "none"),
            isolation_mode=AgentIsolationMode(
                str(data.get("isolation_mode") or AgentIsolationMode.SHARED_WORKSPACE.value)
            ),
            permission_mode=AgentPermissionMode(
                str(data.get("permission_mode") or AgentPermissionMode.FULL_AUTO.value)
            ),
            source=source,
            path=path,
        )
    except Exception:
        return None


class AgentDefinitionRegistry:
    """Discover builtin, user, and repo-scoped agent definitions."""

    def __init__(self, bob_home: Path, cwd: Path) -> None:
        self._bob_home = bob_home
        self._cwd = cwd
        self._cache: list[AgentDefinition] | None = None

    def list_all(self, *, force_reload: bool = False) -> list[AgentDefinition]:
        if self._cache is not None and not force_reload:
            return list(self._cache)

        merged: dict[str, AgentDefinition] = {
            definition.name.lower(): definition
            for definition in _builtin_definitions()
        }
        for source, directory in (
            ("user", self._bob_home / "agents"),
            ("repo", self._cwd / ".bob" / "agents"),
        ):
            for definition in self._load_directory(directory, source=source):
                merged[definition.name.lower()] = definition

        self._cache = sorted(merged.values(), key=lambda item: item.name.lower())
        return list(self._cache)

    def find(self, name: str, *, force_reload: bool = False) -> Optional[AgentDefinition]:
        wanted = (name or "").strip().lower()
        if not wanted:
            return None
        for definition in self.list_all(force_reload=force_reload):
            if definition.name.lower() == wanted:
                return definition.model_copy(deep=True)
        return None

    def _load_directory(self, directory: Path, *, source: str) -> list[AgentDefinition]:
        if not directory.exists():
            return []

        out: list[AgentDefinition] = []
        try:
            for entry in sorted(directory.iterdir()):
                if entry.is_file() and entry.suffix.lower() == ".toml":
                    definition = _load_definition_from_toml(entry, source=source)
                    if definition is not None:
                        out.append(definition)
                    continue
                if not entry.is_dir():
                    continue
                definition = _load_definition_from_toml(entry / "agent.toml", source=source)
                if definition is not None:
                    out.append(definition)
        except PermissionError:
            return out
        return out


def _builtin_definitions() -> list[AgentDefinition]:
    readonly_tools = [
        "list_dir",
        "read_file",
        "read_pdf",
        "glob_files",
        "grep_files",
        "view_image",
        "web_search",
        "web_fetch",
        "tool_search",
        "mcp_list_resources",
        "mcp_read_resource",
        "browser",
    ]
    coding_tools = [
        "shell",
        "list_dir",
        "read_file",
        "read_pdf",
        "write_file",
        "edit_file",
        "glob_files",
        "grep_files",
        "view_image",
        "web_search",
        "web_fetch",
        "tool_search",
        "todo_write",
        "notebook_read",
        "notebook_edit",
        "browser",
        "mcp_list_resources",
        "mcp_read_resource",
    ]
    return [
        AgentDefinition(
            name="worker",
            description="General-purpose background worker for bounded subtasks.",
            instructions=(
                "You are a focused background worker. The lead agent decides your task, not a "
                "hardcoded persona. You may be asked to plan, inspect, implement, review, or "
                "debug. Complete the assigned task, stay within scope, and return a concise "
                "summary of what you changed or found."
            ),
            allowed_tools=coding_tools,
            fork_mode="none",
            isolation_mode=AgentIsolationMode.GIT_WORKTREE,
            permission_mode=AgentPermissionMode.FULL_AUTO,
        ),
        AgentDefinition(
            name="researcher",
            description="Read-only researcher for documentation, repo analysis, and web findings.",
            instructions=(
                "Act as a researcher. Gather relevant evidence from the codebase and the web, "
                "then return sourced findings and practical recommendations."
            ),
            allowed_tools=readonly_tools,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.SHARED_WORKSPACE,
            permission_mode=AgentPermissionMode.READ_ONLY,
        ),
    ]
