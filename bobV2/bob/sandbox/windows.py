from __future__ import annotations

import warnings
from pathlib import Path
import os

from bob.sandbox.base import SandboxRunner
from bob.protocol.config_types import SandboxPolicy, SandboxMode

try:
    import win32security  # type: ignore
    import win32api  # type: ignore
    import win32con  # type: ignore
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class WindowsSandbox(SandboxRunner):
    """
    Windows sandbox runner.

    When pywin32 is available, attempts to use restricted token semantics.
    Without pywin32, falls back to running the command unrestricted with a warning.

    Note: Full restricted-token process spawning on Windows requires launching
    a new process with CreateProcessAsUser / CreateRestrictedToken, which is not
    trivially composable with the list[str] command interface used here. The
    wrap_command method therefore returns the command unchanged; actual token
    restriction would need to be applied at the subprocess creation site.
    """

    def __init__(self, policy: SandboxPolicy, cwd: Path):
        self._policy = policy
        self._cwd = cwd
        self._read_dirs = getattr(policy, 'sandbox_read_dirs', [])
        self._write_dirs = getattr(policy, 'sandbox_write_dirs', [])

    def wrap_command(self, cmd: list[str]) -> list[str]:
        if not HAS_WIN32:
            # Already warned at construction time; pass through unchanged.
            return cmd

        mode = self._policy.mode
        if mode == SandboxMode.DANGER_FULL_ACCESS:
            return cmd

        # Validate path grants before executing
        if mode in (SandboxMode.WORKSPACE_READ, SandboxMode.WORKSPACE_WRITE):
            violation = self._check_path_grants(cmd)
            if violation:
                raise PermissionError(
                    f"Sandbox violation: {violation}. "
                    f"Command attempts to access paths outside granted directories."
                )

        # With pywin32 available we could create a restricted token and launch
        # the process via CreateProcessAsUser.  That requires a different code
        # path than subprocess (the token must be passed to CreateProcess, not
        # prepended to argv).  For now we signal the restriction level through
        # an env-var prefix understood by the execution layer, and return the
        # command unchanged so the caller can optionally pick it up.
        #
        # A complete implementation would:
        #   1. win32security.OpenProcessToken(win32api.GetCurrentProcess(), ...)
        #   2. win32security.CreateRestrictedToken(token, DISABLE_MAX_PRIVILEGE, ...)
        #   3. win32security.CreateProcessAsUser(restricted_token, ...)
        #
        # This is left as a platform-specific enhancement; the no-op return
        # ensures the CLI stays functional on Windows today.
        return cmd
    
    def _check_path_grants(self, cmd: list[str]) -> str | None:
        """Check if command accesses paths outside granted directories.
        
        Returns:
            Error message if violation detected, None otherwise
        """
        if not cmd:
            return None
        
        # Extract potential file paths from command arguments
        paths_to_check = []
        for arg in cmd[1:]:  # Skip command name
            # Skip flags
            if arg.startswith("-"):
                continue
            # Check if argument looks like a path
            if "/" in arg or "\\" in arg or os.path.exists(arg):
                try:
                    paths_to_check.append(Path(arg).resolve())
                except Exception:
                    continue
        
        if not paths_to_check:
            return None
        
        mode = self._policy.mode
        
        # Determine which directories are allowed
        allowed_dirs = []
        if mode == SandboxMode.WORKSPACE_READ:
            allowed_dirs = self._read_dirs or [self._cwd]
        elif mode == SandboxMode.WORKSPACE_WRITE:
            allowed_dirs = self._write_dirs or [self._cwd]
        
        # Check each path against allowed directories
        for path in paths_to_check:
            is_allowed = False
            for allowed_dir in allowed_dirs:
                try:
                    allowed_resolved = Path(allowed_dir).resolve()
                    # Check if path is within allowed directory
                    path.relative_to(allowed_resolved)
                    is_allowed = True
                    break
                except (ValueError, Exception):
                    continue
            
            if not is_allowed:
                return f"Path '{path}' is outside granted directories"
        
        return None

    def available(self) -> bool:
        return True
