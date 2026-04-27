from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _repo_root(cwd: Path) -> Optional[Path]:
    rc, out, _ = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    return Path(out) if rc == 0 and out else None


def _is_git_repo(cwd: Path) -> bool:
    rc, _, _ = _run(["git", "rev-parse", "--git-dir"], cwd)
    return rc == 0


class WorktreeManager:
    """Manages per-agent git worktrees. Falls back gracefully if not in a git repo."""

    def __init__(self, main_cwd: Path) -> None:
        self._main_cwd = main_cwd
        self._worktrees: dict[str, Path] = {}   # agent_id → worktree path
        self._branches: dict[str, str] = {}      # agent_id → branch name

    def create(self, agent_id: str) -> Optional[Path]:
        """
        Create an isolated git worktree for agent_id.
        Returns the worktree path, or None if not in a git repo.
        """
        if not _is_git_repo(self._main_cwd):
            return None

        root = _repo_root(self._main_cwd)
        if root is None:
            return None

        branch = f"bob-agent-{agent_id}"
        worktree_path = root / ".bob_worktrees" / agent_id
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        rc, _, err = _run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path), "HEAD"],
            cwd=root,
        )
        if rc != 0:
            return None

        self._worktrees[agent_id] = worktree_path
        self._branches[agent_id] = branch
        return worktree_path

    def merge_and_cleanup(self, agent_id: str) -> tuple[bool, str]:
        """
        Commit changes in worktree, squash-merge to main working tree, then remove worktree.
        Returns (success, status_message).
        """
        worktree_path = self._worktrees.get(agent_id)
        if worktree_path is None or not worktree_path.exists():
            return True, "no worktree"

        branch = self._branches.get(agent_id, f"bob-agent-{agent_id}")
        root = _repo_root(self._main_cwd)

        # Check for changes in worktree
        rc, status_out, _ = _run(["git", "status", "--porcelain"], worktree_path)
        has_changes = bool(status_out.strip())

        merge_msg = "no changes"
        if has_changes:
            _run(["git", "add", "-A"], worktree_path)
            _run(["git", "commit", "-m", f"agent({agent_id}): task result"], worktree_path)

            if root:
                rc_m, _, err_m = _run(
                    ["git", "merge", "--squash", branch], cwd=self._main_cwd
                )
                if rc_m == 0:
                    _run(
                        ["git", "commit", "-m", f"agent({agent_id}): merged result", "--allow-empty"],
                        cwd=self._main_cwd,
                    )
                    merge_msg = "merged to main"
                else:
                    merge_msg = f"merge conflict (manual resolution needed): {err_m[:120]}"

        self._cleanup(agent_id, root, branch)
        return True, merge_msg

    def cleanup_no_merge(self, agent_id: str) -> None:
        """Remove the worktree without merging (agent failed or was cancelled)."""
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
