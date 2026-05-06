from __future__ import annotations

from pathlib import Path

from bob.protocol.items import SkillMetadata, SkillsListEntry


def list_demo_skill_entries() -> list[SkillsListEntry]:
    base = Path.home() / ".bob" / "skills"
    skills = [
        SkillMetadata(
            name="code-review",
            description="Review a diff or pull request for bugs, regressions, missing tests, and risky behavior.",
            path=base / "code-review",
            scope="user",
            user_invocable=True,
            allowed_tools=["read_file", "grep_files", "shell"],
            content_file="SKILL.md",
        ),
        SkillMetadata(
            name="fix-ci",
            description="Inspect failing CI jobs, summarize logs, and implement the smallest targeted fix.",
            path=base / "fix-ci",
            scope="user",
            user_invocable=True,
            allowed_tools=["shell", "read_file", "edit_file"],
            content_file="SKILL.md",
        ),
        SkillMetadata(
            name="release-notes",
            description="Generate concise release notes from commits, pull requests, and issue references.",
            path=base / "release-notes",
            scope="user",
            user_invocable=True,
            allowed_tools=["shell", "grep_files"],
            content_file="SKILL.md",
        ),
        SkillMetadata(
            name="frontend-polish",
            description="Audit UI spacing, responsive layout, accessibility states, and visual consistency.",
            path=base / "frontend-polish",
            scope="user",
            user_invocable=True,
            allowed_tools=["read_file", "shell", "browser"],
            content_file="SKILL.md",
        ),
    ]
    return [SkillsListEntry(cwd=base, skills=skills)]
