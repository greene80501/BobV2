from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentTemplate:
    system_prompt_suffix: str
    allowed_tools: set[str] = field(default_factory=set)  # empty = allow all


AGENT_TEMPLATES: dict[str, AgentTemplate] = {
    "explore": AgentTemplate(
        system_prompt_suffix=(
            "You are a fast filesystem exploration agent. "
            "Your job is to read and search files to answer questions. "
            "Do NOT write, edit, or delete any files."
        ),
        allowed_tools={"shell", "list_dir", "glob_files", "grep_files", "read_file"},
    ),
    "plan": AgentTemplate(
        system_prompt_suffix=(
            "You are a planning agent. "
            "Analyse the codebase and produce a detailed implementation plan. "
            "Do NOT write or modify any files — only read."
        ),
        allowed_tools={"read_file", "glob_files", "grep_files", "list_dir", "update_plan"},
    ),
    "verify": AgentTemplate(
        system_prompt_suffix=(
            "You are a verification and code-review agent. "
            "Run tests, check correctness, and report findings. "
            "Do NOT make changes to source files."
        ),
        allowed_tools={"shell", "read_file", "glob_files", "grep_files"},
    ),
    "write": AgentTemplate(
        system_prompt_suffix=(
            "You are a focused implementation agent. "
            "Write and edit code files to complete the assigned task."
        ),
        allowed_tools=set(),  # all tools
    ),
}


def get_template(name: str) -> AgentTemplate | None:
    return AGENT_TEMPLATES.get(name)
