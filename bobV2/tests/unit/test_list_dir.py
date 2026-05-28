from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bob.tools.list_dir import list_dir_handler


def _ctx(tmp_path: Path):
    return SimpleNamespace(cwd=tmp_path)


@pytest.mark.asyncio
async def test_list_dir_lists_basic_entries(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("ok", encoding="utf-8")

    out = await list_dir_handler({"path": "."}, _ctx(tmp_path))

    assert "src/" in out
    assert "README.md" in out


@pytest.mark.asyncio
async def test_list_dir_handles_symlink_entries_without_follow_symlinks_kwarg(tmp_path: Path) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    link = tmp_path / "target-link"
    try:
        link.symlink_to(target_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    out = await list_dir_handler({"path": "."}, _ctx(tmp_path))

    assert "target/" in out or "target-link@ ->" in out


@pytest.mark.asyncio
async def test_list_dir_recovers_from_redundant_workspace_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "bobV2"
    workspace.mkdir()
    (workspace / "bob").mkdir()

    out = await list_dir_handler({"path": "bobV2"}, _ctx(workspace))

    assert "bob/" in out


@pytest.mark.asyncio
async def test_list_dir_returns_file_guidance_for_file_paths(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("ok", encoding="utf-8")

    out = await list_dir_handler({"path": "README.md"}, _ctx(tmp_path))

    assert "This path is a file" in out
    assert "use read_file" in out
