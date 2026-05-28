from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bob.tools.read_file import read_file_handler


def _ctx(tmp_path: Path):
    return SimpleNamespace(cwd=tmp_path)


@pytest.mark.asyncio
async def test_read_file_recovers_from_redundant_workspace_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "bobV2"
    workspace.mkdir()
    readme = workspace / "README.md"
    readme.write_text("hello\n", encoding="utf-8")

    out = await read_file_handler({"path": "bobV2/README.md"}, _ctx(workspace))

    assert out == "hello\n"


@pytest.mark.asyncio
async def test_read_file_returns_directory_guidance_for_directory_paths(tmp_path: Path) -> None:
    folder = tmp_path / "bob"
    folder.mkdir()

    out = await read_file_handler({"path": "bob"}, _ctx(tmp_path))

    assert "This path is a directory" in out
    assert "use list_dir" in out
