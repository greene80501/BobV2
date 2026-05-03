from __future__ import annotations

import subprocess
from pathlib import Path

from bob.core.agents.worktree import WorktreeManager


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)


def test_worktree_create_and_merge_without_auto_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "bob@example.com"], repo)
    _run(["git", "config", "user.name", "Bob"], repo)
    (repo / "app.txt").write_text("one\n", encoding="utf-8")
    _run(["git", "add", "app.txt"], repo)
    _run(["git", "commit", "-m", "init"], repo)

    manager = WorktreeManager(repo)
    worktree = manager.create("abc12345")

    assert worktree is not None
    (worktree / "app.txt").write_text("two\n", encoding="utf-8")

    ok, msg = manager.merge_and_cleanup("abc12345")

    assert ok is True
    assert "squash-merged" in msg
    assert (repo / "app.txt").read_text(encoding="utf-8") == "two\n"
    status = _run(["git", "status", "--porcelain"], repo).stdout
    assert "M  app.txt" in status or "M app.txt" in status
