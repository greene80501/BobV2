from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

AGENTS_MD_FILENAME = "AGENTS.md"

AGENTS_MD_INIT_TEMPLATE = """\
# Project Instructions for Bob

## Code Style
- Follow existing conventions in the codebase
- Keep changes minimal and focused

## Project Structure
- [Describe key directories and their purpose]

## Testing
- [How to run tests: e.g., `pytest tests/`]

## Notes
- [Any other context useful for the AI assistant]
"""


def load_agents_md(cwd: Path, bob_home: Path) -> Optional[str]:
    """
    Load and concatenate AGENTS.md files from the directory hierarchy.

    Search order (lowest → highest priority):
      1. ``~/.bob/AGENTS.md`` (global user instructions)
      2. AGENTS.md files found walking *upward* from the filesystem root
         to *cwd*, ordered from root → cwd.

    The final string is assembled so that the highest-priority file
    (closest to *cwd*) appears last — matching the convention that later
    content overrides earlier content.

    Returns ``None`` if no AGENTS.md files are found.
    """
    # Walk up from cwd to filesystem root, collecting AGENTS.md files.
    # We traverse upward so that the deepest (most specific) file is at
    # index 0 of *found*; we reverse at the end.
    found: list[tuple[Path, str]] = []

    current = cwd.resolve()
    while True:
        candidate = current / AGENTS_MD_FILENAME
        if candidate.is_file():
            try:
                content = candidate.read_text(encoding="utf-8")
                if content.strip():
                    found.append((current, content))
            except OSError:
                pass
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Add global ~/.bob/AGENTS.md (lowest priority, appended last before reversing)
    global_agents = bob_home / AGENTS_MD_FILENAME
    if global_agents.is_file():
        try:
            content = global_agents.read_text(encoding="utf-8")
            if content.strip():
                found.append((bob_home, content))
        except OSError:
            pass

    if not found:
        return None

    # Reverse: global first (lowest priority), project-root first, cwd last (highest)
    found.reverse()

    sections: list[str] = []
    for location, content in found:
        header = f"# Instructions from {location / AGENTS_MD_FILENAME}"
        sections.append(f"{header}\n\n{content.strip()}")

    return "\n\n---\n\n".join(sections)


def create_agents_md(cwd: Path) -> Path:
    """Create an AGENTS.md in *cwd* populated with the starter template."""
    path = cwd / AGENTS_MD_FILENAME
    if not path.exists():
        path.write_text(AGENTS_MD_INIT_TEMPLATE, encoding="utf-8")
    return path


async def generate_agents_md(cwd: Path, session: Any) -> Path:
    """Generate AGENTS.md using the model to analyze the current project.

    Falls back to the static template if the model call fails.
    """
    import os

    path = cwd / AGENTS_MD_FILENAME
    if path.exists():
        return path

    # Collect a sample of project files for context
    sample_files: list[str] = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
    try:
        for root, dirs, fnames in os.walk(str(cwd)):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in fnames:
                rel = os.path.relpath(os.path.join(root, fname), str(cwd))
                sample_files.append(rel)
                if len(sample_files) >= 30:
                    break
            if len(sample_files) >= 30:
                break
    except Exception:
        pass

    file_list = "\n".join(sample_files[:30]) or "(no files found)"
    prompt = (
        f"You are analyzing a software project to generate an AGENTS.md file.\n\n"
        f"Project directory: {cwd}\n"
        f"Sample file paths:\n{file_list}\n\n"
        "Write a concise AGENTS.md for this project. Include:\n"
        "1. Brief project description\n"
        "2. Code style conventions\n"
        "3. How to run tests\n"
        "4. Key directory structure\n"
        "5. Any important notes for an AI assistant working on this code\n\n"
        "Output ONLY the AGENTS.md content — no preamble or explanation."
    )

    try:
        from bob.llm.client import TextDeltaEvent

        content_parts: list[str] = []
        async for event in session.client.stream_turn(
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            instructions="",
            tools=[],
        ):
            if isinstance(event, TextDeltaEvent):
                content_parts.append(event.delta)

        content = "".join(content_parts).strip()
    except Exception:
        content = ""

    if not content:
        content = AGENTS_MD_INIT_TEMPLATE

    path.write_text(content, encoding="utf-8")
    return path
