from __future__ import annotations

import datetime
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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
