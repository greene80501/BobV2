from __future__ import annotations

from pathlib import Path
from typing import Optional

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
    """
    Create an AGENTS.md in *cwd* populated with the starter template.

    Does nothing if the file already exists.  Returns the path to the file.
    """
    path = cwd / AGENTS_MD_FILENAME
    if not path.exists():
        path.write_text(AGENTS_MD_INIT_TEMPLATE, encoding="utf-8")
    return path
