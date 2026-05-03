from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _repo_root(cwd: Path) -> Optional[Path]:
    rc, out, _ = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(out) if rc == 0 and out else None


def _is_git_repo(cwd: Path) -> bool:
    rc, _, _ = _run(["git", "rev-parse", "--git-dir"], cwd)
    return rc == 0


class WorktreeManager:
    """Manage per-agent git worktrees and squash-merge their results locally."""

    def __init__(self, main_cwd: Path) -> None:
        self._main_cwd = main_cwd
        self._worktrees: dict[str, Path] = {}
        self._branches: dict[str, str] = {}

    def create(self, agent_id: str) -> Optional[Path]:
        if not _is_git_repo(self._main_cwd):
            return None

        root = _repo_root(self._main_cwd)
        if root is None:
            return None

        branch = f"bob-agent-{agent_id}"
        worktree_path = root / ".bob_worktrees" / agent_id
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        rc, _, _ = _run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path), "HEAD"],
            cwd=root,
        )
        if rc != 0:
            return None

        self._worktrees[agent_id] = worktree_path
        self._branches[agent_id] = branch
        return worktree_path

    def merge_and_cleanup(self, agent_id: str) -> tuple[bool, str]:
        worktree_path = self._worktrees.get(agent_id)
        if worktree_path is None or not worktree_path.exists():
            return True, "no worktree"

        branch = self._branches.get(agent_id, f"bob-agent-{agent_id}")
        root = _repo_root(self._main_cwd)

        _, status_out, _ = _run(["git", "status", "--porcelain"], worktree_path)
        has_changes = bool(status_out.strip())
        if not has_changes:
            self._cleanup(agent_id, root, branch)
            return True, "no changes"

        _run(["git", "add", "-A"], worktree_path)
        _run(["git", "commit", "-m", f"agent({agent_id}): task result"], worktree_path)

        if root is None:
            self._cleanup(agent_id, root, branch)
            return True, "worktree committed but repo root was not available"

        rc_merge, _, err_merge = _run(
            ["git", "merge", "--squash", "--no-commit", branch],
            cwd=self._main_cwd,
        )
        if rc_merge != 0:
            return (
                False,
                (
                    "merge conflict (worktree preserved for manual resolution): "
                    f"{err_merge[:120]} path={worktree_path} branch={branch}"
                ),
            )

        self._cleanup(agent_id, root, branch)
        return True, "squash-merged into main working tree"

    def cleanup_no_merge(self, agent_id: str) -> None:
        root = _repo_root(self._main_cwd)
        branch = self._branches.get(agent_id, f"bob-agent-{agent_id}")
        self._cleanup(agent_id, root, branch)

    def _cleanup(self, agent_id: str, root: Optional[Path], branch: str) -> None:
        worktree_path = self._worktrees.pop(agent_id, None)
        self._branches.pop(agent_id, None)
        ref = root or self._main_cwd
        if worktree_path and worktree_path.exists():
            _run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=ref)
        _run(["git", "branch", "-D", branch], cwd=ref)
