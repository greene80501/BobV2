from __future__ import annotations

import datetime
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _format_tree_name(path: Path, is_dir: bool) -> str:
    return f"{path.name}/" if is_dir else path.name


def _list_top_level_entries(root: Path) -> list[Path]:
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    return sorted(entries, key=lambda p: (not p.is_dir(), p.name.lower()))


def _build_workspace_snapshot(cwd: Path) -> str:
    entries = _list_top_level_entries(cwd)
    if not entries:
        return f"Startup workspace snapshot:\n- cwd: {cwd}\n- top_level_items:\n  - (empty or unreadable)"

    lines = [
        "Startup workspace snapshot:",
        f"- cwd: {cwd}",
        "- top_level_items:",
    ]
    for entry in entries:
        lines.append(f"  - {_format_tree_name(entry, entry.is_dir())}")

    return "\n".join(lines)


@dataclass
class EnvironmentContext:
    """
    Snapshot of the execution environment captured at the start of each turn.

    Attributes
    ----------
    os_name:      Platform name (Linux, Darwin, Windows).
    os_version:   Detailed OS version string.
    cwd:          Current working directory as a string.
    shell:        Active shell binary (SHELL / COMSPEC).
    home:         User home directory.
    timestamp:    ISO-8601 UTC timestamp of capture.
    git_branch:   Current git branch, or None if not in a git repo.
    git_status:   Short description of working-tree state, or None.
    """

    os_name: str
    os_version: str
    cwd: str
    shell: str
    home: str
    timestamp: str
    git_branch: Optional[str]
    git_status: Optional[str]
    workspace_snapshot: str

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, cwd: Path) -> "EnvironmentContext":
        """Capture the current environment relative to *cwd*."""
        os_name = platform.system()
        os_version = platform.version()
        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC", "unknown")
        home = str(Path.home())
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        git_branch: Optional[str] = None
        git_status: Optional[str] = None
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=2,
            )
            if result.returncode == 0:
                git_branch = result.stdout.strip() or None

            result2 = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=2,
            )
            if result2.returncode == 0:
                lines = [l for l in result2.stdout.strip().splitlines() if l.strip()]
                git_status = f"{len(lines)} changes" if lines else "clean"
        except Exception:
            pass

        return cls(
            os_name=os_name,
            os_version=os_version,
            cwd=str(cwd),
            shell=shell,
            home=home,
            timestamp=timestamp,
            git_branch=git_branch,
            git_status=git_status,
            workspace_snapshot=_build_workspace_snapshot(cwd),
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_prompt_text(self) -> str:
        """Format environment info suitable for injection into a system prompt."""
        lines = [
            f"OS: {self.os_name} {self.os_version}",
            f"CWD: {self.cwd}",
            f"Shell: {self.shell}",
            f"Home: {self.home}",
            f"Time: {self.timestamp}",
        ]
        if self.git_branch:
            git_line = f"Git: {self.git_branch}"
            if self.git_status:
                git_line += f" ({self.git_status})"
            lines.append(git_line)

        if self.os_name == "Windows":
            lines.append(
                "Shell: PowerShell (commands are auto-wrapped — do NOT call "
                "'powershell' or 'powershell.exe' yourself). "
                "Use cmdlets directly: `ls`/`Get-ChildItem`, `cat`/`Get-Content`, "
                "`pwd`, `mkdir`, `rm`/`Remove-Item`, `cp`/`Copy-Item`, "
                "`mv`/`Move-Item`, `Select-String` (grep). "
                "Use semicolons (;) not && for chaining. "
                "Paths use backslashes or forward slashes."
            )

        if self.workspace_snapshot:
            lines.append(self.workspace_snapshot)
            lines.append(
                "Treat the startup workspace snapshot as the authoritative starting state. "
                "Do not spend your first tool calls rediscovering the current directory or its top-level items "
                "unless you need a refreshed view because the workspace may have changed."
            )
            lines.append(
                "Treat the current working directory shown above as the workspace root for this session. "
                "Do not probe parent directories with `..` unless the user explicitly asks for paths outside the current workspace."
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def equals_except_timestamp(self, other: "EnvironmentContext") -> bool:
        """
        Return True if *other* represents the same environment (ignoring timestamp).
        Used to avoid re-injecting an identical environment block into the prompt.
        """
        return (
            self.os_name == other.os_name
            and self.cwd == other.cwd
            and self.shell == other.shell
            and self.git_branch == other.git_branch
        )
