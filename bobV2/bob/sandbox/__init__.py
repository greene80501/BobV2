import sys
from pathlib import Path

from bob.sandbox.base import SandboxRunner, NoSandbox
from bob.protocol.config_types import SandboxPolicy, SandboxMode


def get_sandbox_runner(policy: SandboxPolicy, cwd: Path) -> SandboxRunner:
    """Select the appropriate sandbox runner for the current platform and policy."""
    if policy.mode == SandboxMode.DANGER_FULL_ACCESS:
        return NoSandbox()

    if sys.platform == "darwin":
        from bob.sandbox.macos import SeatbeltSandbox

        runner = SeatbeltSandbox(policy, cwd)
        if runner.available():
            return runner
        return NoSandbox()

    elif sys.platform.startswith("linux"):
        from bob.sandbox.linux import BubblewrapSandbox
        from bob.sandbox.base import NoSandbox as LinuxNoSandbox

        try:
            return BubblewrapSandbox(policy, cwd)
        except Exception:
            return LinuxNoSandbox()

    elif sys.platform == "win32":
        from bob.sandbox.windows import WindowsSandbox

        return WindowsSandbox(policy, cwd)

    return NoSandbox()


__all__ = ["get_sandbox_runner", "SandboxRunner", "NoSandbox"]
