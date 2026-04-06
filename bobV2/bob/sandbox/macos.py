from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from bob.sandbox.base import SandboxRunner
from bob.protocol.config_types import SandboxPolicy, SandboxMode

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# Seatbelt profile templates
_READ_ONLY_PROFILE = """\
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow signal)
(allow file-read*)
(allow file-read-metadata)
(deny file-write*)
(deny network*)
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm-read*)
(allow ipc-posix-shm-write-data)
(allow system-socket)
"""

_WORKSPACE_WRITE_PROFILE_TEMPLATE = """\
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow signal)
(allow file-read*)
(allow file-read-metadata)
(deny file-write*)
(allow file-write*
    (subpath {cwd_literal})
    (subpath "/tmp")
    (subpath "/private/tmp")
    (literal "/dev/null")
    (literal "/dev/tty")
    (literal "/dev/stdout")
    (literal "/dev/stderr"))
(deny network*)
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm-read*)
(allow ipc-posix-shm-write-data)
(allow system-socket)
"""

_DANGER_FULL_ACCESS_PROFILE = """\
(version 1)
(allow default)
"""


def _seatbelt_literal(path: str) -> str:
    """Escape a path for use as a seatbelt literal string."""
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _build_profile(policy: SandboxPolicy, cwd: Path) -> str:
    mode = policy.mode
    if mode == SandboxMode.READ_ONLY:
        return _READ_ONLY_PROFILE
    elif mode == SandboxMode.WORKSPACE_WRITE:
        extra_roots = ""
        for root in policy.writable_roots:
            extra_roots += f"\n    (subpath {_seatbelt_literal(str(root))})"
        profile = _WORKSPACE_WRITE_PROFILE_TEMPLATE.format(
            cwd_literal=_seatbelt_literal(str(cwd.resolve()))
        )
        if extra_roots:
            # Insert extra writable roots into the file-write* allow block
            profile = profile.replace(
                '    (literal "/dev/stderr"))',
                f'    (literal "/dev/stderr"){extra_roots})',
            )
        return profile
    else:
        # DANGER_FULL_ACCESS or unknown
        return _DANGER_FULL_ACCESS_PROFILE


class SeatbeltSandbox(SandboxRunner):
    """
    macOS sandbox using /usr/bin/sandbox-exec with a Seatbelt profile.

    The profile file is written to a temporary file for each wrap_command call.
    The temp file is cleaned up after the command finishes (caller responsibility
    to not reuse the returned args after the tempfile is deleted — the profile
    path in the returned list points to a file that persists as long as the
    tempfile object lives).

    For long-lived use, hold a reference to this instance; it manages a single
    profile file whose path is stable across wrap_command calls.
    """

    def __init__(self, policy: SandboxPolicy, cwd: Path):
        self._policy = policy
        self._cwd = cwd
        self._profile_text = _build_profile(policy, cwd)
        self._tmpfile: Optional[tempfile.NamedTemporaryFile] = None
        self._profile_path: Optional[str] = None

    def _ensure_profile_file(self) -> str:
        """Write profile to a temp file and return its path."""
        if self._profile_path is not None:
            return self._profile_path
        # Write to a persistent temp file (deleted when this object is GC'd)
        self._tmpfile = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".sb",
            prefix="bob_seatbelt_",
            delete=False,
            encoding="utf-8",
        )
        self._tmpfile.write(self._profile_text)
        self._tmpfile.flush()
        self._tmpfile.close()
        self._profile_path = self._tmpfile.name
        return self._profile_path

    def wrap_command(self, cmd: list[str]) -> list[str]:
        profile_path = self._ensure_profile_file()
        return [SANDBOX_EXEC, "-f", profile_path] + cmd

    def available(self) -> bool:
        return os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)

    def __del__(self) -> None:
        if self._profile_path:
            try:
                os.unlink(self._profile_path)
            except OSError:
                pass
