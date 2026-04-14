from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from bob.app_server.router import RpcRouter
from bob.app_server.routes import files as files_routes


def test_files_grep_uses_ripgrep_when_available(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("bob.app_server.routes.files.shutil.which", lambda name: "rg" if name == "rg" else None)
    monkeypatch.setattr(
        "bob.app_server.routes.files.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="a.txt\nb/c.py\n",
            stderr="",
        ),
    )

    router = RpcRouter()
    files_routes.register(router)
    result = asyncio.run(
        router.dispatch(None, "files.grep", {"pattern": "needle", "root": str(tmp_path)})
    )

    assert result == {
        "matches": [
            {"path": str((tmp_path / "a.txt").resolve())},
            {"path": str((tmp_path / "b" / "c.py").resolve())},
        ]
    }


def test_files_grep_falls_back_when_ripgrep_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("bob.app_server.routes.files.shutil.which", lambda name: None)
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("HELLO WORLD\n", encoding="utf-8")

    router = RpcRouter()
    files_routes.register(router)
    result = asyncio.run(
        router.dispatch(
            None,
            "files.grep",
            {"pattern": "hello world", "root": str(tmp_path), "case_sensitive": False},
        )
    )

    assert {"path": str((tmp_path / "a.txt").resolve())} in result["matches"]
    assert {"path": str((tmp_path / "b.txt").resolve())} in result["matches"]
