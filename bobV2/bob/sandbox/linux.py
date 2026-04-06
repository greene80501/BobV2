from __future__ import annotations

import shutil
from pathlib import Path

from bob.sandbox.base import SandboxRunner, NoSandbox
from bob.protocol.config_types import SandboxPolicy, SandboxMode

BWRAP_BINARY = "bwrap"


def _find_bwrap() -> str | None:
    return shutil.which(BWRAP_BINARY)


def _build_bwrap_args(policy: SandboxPolicy, cwd: Path) -> list[str]:
    """Build the bwrap argument list based on the sandbox policy."""
    mode = policy.mode
    args: list[str] = []

    if mode == SandboxMode.DANGER_FULL_ACCESS:
        args += ["--dev-bind", "/", "/"]
        return args

    if mode == SandboxMode.READ_ONLY:
        args += [
            "--ro-bind", "/", "/",
            "--unshare-net",
        ]
    elif mode == SandboxMode.WORKSPACE_WRITE:
        cwd_str = str(cwd.resolve())
        args += [
            "--ro-bind", "/", "/",
            "--bind", cwd_str, cwd_str,
            "--bind", "/tmp", "/tmp",
            "--unshare-net",
        ]
        # Additional writable roots from policy
        for root in policy.writable_roots:
            root_str = str(root.resolve())
            args += ["--bind", root_str, root_str]
    else:
        # Unknown mode — fall back to read-only
        args += [
            "--ro-bind", "/", "/",
            "--unshare-net",
        ]

    # Common bind mounts needed for most commands
    args += [
        "--proc", "/proc",
        "--dev", "/dev",
    ]

    return args


class BubblewrapSandbox(SandboxRunner):
    """
    Linux sandbox using bubblewrap (bwrap).

    Raises RuntimeError at construction time if bwrap is not available.
    """

    def __init__(self, policy: SandboxPolicy, cwd: Path):
        bwrap = _find_bwrap()
        if bwrap is None:
            raise RuntimeError("bwrap not found on PATH")
        self._bwrap = bwrap
        self._policy = policy
        self._cwd = cwd
        self._bwrap_args = _build_bwrap_args(policy, cwd)

    def wrap_command(self, cmd: list[str]) -> list[str]:
        return [self._bwrap] + self._bwrap_args + ["--"] + cmd

    def available(self) -> bool:
        return _find_bwrap() is not None


__all__ = ["BubblewrapSandbox", "NoSandbox"]
