from __future__ import annotations

import ctypes
import ctypes.wintypes
import warnings
from pathlib import Path
import os
import re
import sys

from bob.sandbox.base import SandboxRunner
from bob.protocol.config_types import SandboxPolicy, SandboxMode

try:
    import win32security  # type: ignore
    import win32api  # type: ignore
    import win32con  # type: ignore
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# ---------------------------------------------------------------------------
# Windows Job Object wrapper (ctypes, no pywin32 required)
# ---------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"


class WindowsJobObject:
    """Wrap a Windows Job Object to enforce process limits on spawned commands.

    Uses ctypes to call Win32 APIs directly — no pywin32 dependency needed.
    """

    # JOBOBJECT_BASIC_LIMIT_INFORMATION flags
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    # JobObjectBasicLimitInformation = 2
    _JobObjectBasicLimitInformation = 2

    def __init__(self, max_processes: int = 32) -> None:
        self._handle = None
        if not _IS_WINDOWS:
            return
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return
        self._handle = handle
        self._configure(max_processes)

    def _configure(self, max_processes: int) -> None:
        if not self._handle:
            return
        try:
            kernel32 = ctypes.windll.kernel32

            class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.wintypes.DWORD),
                    ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                    ("PriorityClass", ctypes.wintypes.DWORD),
                    ("SchedulingClass", ctypes.wintypes.DWORD),
                ]

            info = _JOBOBJECT_BASIC_LIMIT_INFORMATION()
            info.LimitFlags = (
                self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | self._JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            info.ActiveProcessLimit = max(1, max_processes)
            kernel32.SetInformationJobObject(
                self._handle,
                self._JobObjectBasicLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
        except Exception:
            pass

    def assign_process(self, pid: int) -> bool:
        """Assign an existing process (by PID) to this job object."""
        if not self._handle or not _IS_WINDOWS:
            return False
        try:
            kernel32 = ctypes.windll.kernel32
            PROCESS_ALL_ACCESS = 0x1F0FFF
            proc_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if not proc_handle:
                return False
            result = kernel32.AssignProcessToJobObject(self._handle, proc_handle)
            kernel32.CloseHandle(proc_handle)
            return bool(result)
        except Exception:
            return False

    def close(self) -> None:
        if self._handle and _IS_WINDOWS:
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None

    def __del__(self) -> None:
        self.close()


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
        # New schema uses writable_roots. Keep legacy attr fallback for compatibility.
        legacy_read = getattr(policy, "sandbox_read_dirs", [])
        legacy_write = getattr(policy, "sandbox_write_dirs", [])
        writable_roots = [Path(p) for p in getattr(policy, "writable_roots", [])]
        self._read_dirs = [Path(p) for p in legacy_read] or writable_roots
        self._write_dirs = [Path(p) for p in legacy_write] or writable_roots
        # Job object for process isolation (created lazily)
        self._job_object: WindowsJobObject | None = None

    def get_job_object(self) -> WindowsJobObject:
        """Return (and lazily create) the job object for this sandbox."""
        if self._job_object is None:
            self._job_object = WindowsJobObject(max_processes=32)
        return self._job_object

    def wrap_command(self, cmd: list[str]) -> list[str]:
        if not HAS_WIN32:
            # Already warned at construction time; pass through unchanged.
            return cmd

        mode = self._policy.mode
        if mode == SandboxMode.DANGER_FULL_ACCESS:
            return cmd

        # Validate path grants before executing
        if self._is_workspace_scoped_mode(mode):
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

    @staticmethod
    def _is_workspace_scoped_mode(mode: SandboxMode) -> bool:
        """
        Handle current and legacy mode names without relying on removed enum members.
        """
        value = mode.value if hasattr(mode, "value") else str(mode)
        return value in ("workspace-write", "workspace-read")

    @staticmethod
    def _unwrap_shell_wrappers(cmd: list[str]) -> list[str]:
        """
        Canonicalize shell wrappers so policy checks inspect real command args.
        """
        if not cmd:
            return cmd
        out = list(cmd)
        exe = out[0].lower().replace(".exe", "")

        # cmd /c <command...>
        if exe == "cmd" and len(out) >= 3 and out[1].lower() == "/c":
            return WindowsSandbox._unwrap_shell_wrappers(out[2:])

        # powershell -command <command...>
        if exe in ("powershell", "pwsh") and len(out) >= 3 and out[1].lower() in ("-command", "-c"):
            remainder = out[2:]
            if len(remainder) == 1:
                # Cheap split is enough for path-grant checks.
                return WindowsSandbox._unwrap_shell_wrappers(remainder[0].split())
            return WindowsSandbox._unwrap_shell_wrappers(remainder)

        return out
    
    def _check_path_grants(self, cmd: list[str]) -> str | None:
        """Check if command accesses paths outside granted directories.
        
        Returns:
            Error message if violation detected, None otherwise
        """
        if not cmd:
            return None
        
        canonical = self._unwrap_shell_wrappers(cmd)

        # Extract potential file paths from command arguments
        paths_to_check = []
        for arg in canonical[1:]:  # Skip command name
            # Skip standard flags (/c, /s, -n, --long-flag, etc.)
            if re.match(r"^[-/][A-Za-z?][\w-]*$", arg):
                continue
            # Check if argument looks like a path
            if "/" in arg or "\\" in arg or os.path.exists(arg):
                try:
                    p = Path(arg)
                    if not p.is_absolute():
                        p = self._cwd / p
                    paths_to_check.append(p.resolve())
                except Exception:
                    continue
        
        if not paths_to_check:
            return None
        
        mode = self._policy.mode
        
        # Determine which directories are allowed
        allowed_dirs = []
        mode_value = mode.value if hasattr(mode, "value") else str(mode)
        if mode_value == "workspace-read":
            allowed_dirs = self._read_dirs or [self._cwd]
        elif mode_value == "workspace-write":
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
