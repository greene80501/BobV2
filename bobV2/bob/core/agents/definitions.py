from __future__ import annotations

from pathlib import Path
from typing import Optional

from bob.core.agents.runtime import (
    AgentDefinition,
    AgentMode,
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
            mode=AgentMode(str(data.get("mode") or AgentMode.ALL.value)),
            hidden=bool(data.get("hidden", False)),
            model=(str(data.get("model")).strip() if data.get("model") else None),
            prompt=(str(data.get("prompt")).strip() if data.get("prompt") else None),
            color=(str(data.get("color")).strip() if data.get("color") else None),
            steps=(int(data.get("steps")) if data.get("steps") is not None else None),
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
    planning_tools = [
        "list_dir",
        "read_file",
        "read_pdf",
        "glob_files",
        "grep_files",
        "view_image",
        "web_search",
        "web_fetch",
        "tool_search",
        "request_user_input",
        "mcp_list_resources",
        "mcp_read_resource",
        "browser",
    ]
    return [
        AgentDefinition(
            name="build",
            description="Primary coding agent with the full Bob tool surface.",
            instructions=(
                "You are the primary coding agent. Execute tools directly, stay outcome-focused, "
                "and prefer completing the task in the current thread unless delegation is useful."
            ),
            allowed_tools=coding_tools,
            mode=AgentMode.PRIMARY,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.GIT_WORKTREE,
            permission_mode=AgentPermissionMode.FULL_AUTO,
        ),
        AgentDefinition(
            name="plan",
            description="Planning-first primary agent that avoids mutating tools.",
            instructions=(
                "You are in planning mode. Produce decision-complete plans and avoid mutating the "
                "workspace unless the user explicitly exits planning."
            ),
            allowed_tools=planning_tools,
            mode=AgentMode.PRIMARY,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.SHARED_WORKSPACE,
            permission_mode=AgentPermissionMode.READ_ONLY,
        ),
        AgentDefinition(
            name="general",
            description=(
                "General-purpose agent for researching complex questions and executing "
                "multi-step tasks. Use this agent to execute multiple units of work in parallel."
            ),
            instructions=(
                "You are a general-purpose subagent for researching complex questions and executing "
                "multi-step tasks. Complete the assigned task autonomously, stay within scope, and "
                "return a concise result the parent can use immediately."
            ),
            allowed_tools=coding_tools,
            mode=AgentMode.SUBAGENT,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.SHARED_WORKSPACE,
            permission_mode=AgentPermissionMode.FULL_AUTO,
        ),
        AgentDefinition(
            name="explore",
            description=(
                "Fast agent specialized for exploring codebases. Use this when you need "
                "to quickly find files by patterns, search code for keywords, or answer "
                "questions about how the codebase works."
            ),
            instructions=(
                "You are a file search specialist. You excel at thoroughly navigating and exploring codebases.\n\n"
                "Your strengths:\n"
                "- Rapidly finding files using glob patterns\n"
                "- Searching code and text with powerful regex patterns\n"
                "- Reading and analyzing file contents\n\n"
                "Guidelines:\n"
                "- For repo-understanding work, start from top-level structure, key entrypoints, configuration, and tests before going deeper\n"
                "- Use glob_files for broad file pattern matching\n"
                "- Use grep_files for searching file contents with regex\n"
                "- Use read_file when you know the specific file path you need to read\n"
                "- Never pass a directory path to read_file; use list_dir for directories\n"
                "- Adapt your search approach based on the thoroughness level specified by the caller\n"
                "- Return file paths in your final response\n"
                "- Do not create any files or run shell commands that modify the user's system state in any way\n\n"
                "Complete the user's search request efficiently and report your findings clearly."
            ),
            allowed_tools=readonly_tools,
            mode=AgentMode.SUBAGENT,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.SHARED_WORKSPACE,
            permission_mode=AgentPermissionMode.READ_ONLY,
        ),
        AgentDefinition(
            name="scout",
            description="External-docs and dependency-source specialist.",
            instructions=(
                "You are scout, a read-only research agent for external libraries, dependency source, "
                "and documentation.\n\n"
                "Your purpose is to investigate code outside the local workspace and return "
                "evidence-backed findings without modifying the user's workspace.\n\n"
                "Use this agent when asked to:\n"
                "- inspect external documentation or public source references\n"
                "- compare local code against upstream documentation or public implementations\n"
                "- explain how a library or framework works by reading its source and docs\n"
                "- investigate third-party APIs, workflows, or behavior outside the current workspace\n\n"
                "Prefer direct code and documentation evidence over assumptions. Call out uncertainty "
                "clearly instead of smoothing over gaps."
            ),
            allowed_tools=readonly_tools,
            mode=AgentMode.SUBAGENT,
            fork_mode="all",
            isolation_mode=AgentIsolationMode.SHARED_WORKSPACE,
            permission_mode=AgentPermissionMode.READ_ONLY,
        ),
    ]
