from __future__ import annotations

from pathlib import Path

from bob.protocol.config_types import SandboxMode, SandboxPolicy
from bob.sandbox.windows import WindowsSandbox


def test_workspace_mode_check_does_not_reference_removed_enum_members():
    assert WindowsSandbox._is_workspace_scoped_mode(SandboxMode.WORKSPACE_WRITE) is True
    assert WindowsSandbox._is_workspace_scoped_mode(SandboxMode.READ_ONLY) is False


def test_cmd_wrapper_flag_is_not_treated_as_a_path(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    inside = root / "project"
    inside.mkdir()

    sandbox = WindowsSandbox(
        SandboxPolicy(mode=SandboxMode.WORKSPACE_WRITE, cwd=root),
        cwd=root,
    )

    # "/c" is a cmd flag and must not be parsed as a filesystem path.
    violation = sandbox._check_path_grants(["cmd", "/c", "dir", str(inside)])
    assert violation is None

