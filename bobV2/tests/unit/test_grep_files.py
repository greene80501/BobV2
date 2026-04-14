from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

from bob.tools.grep_files import grep_files_handler


def test_grep_files_uses_ripgrep_when_available(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("bob.tools.grep_files.shutil.which", lambda name: "rg" if name == "rg" else None)
    monkeypatch.setattr(
        "bob.tools.grep_files.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="./src/main.py:3:hello\n./.env:1:SECRET=1\n",
            stderr="",
        ),
    )

    out = asyncio.run(
        grep_files_handler(
            {
                "pattern": "hello",
                "max_results": 1,
            },
            SimpleNamespace(cwd=tmp_path),
        )
    )

    assert out == "src/main.py:3:hello\n[...truncated at 1 results]"


def test_grep_files_falls_back_when_ripgrep_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("bob.tools.grep_files.shutil.which", lambda name: None)
    (tmp_path / "a.txt").write_text("Alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("zzz\nALPHA\n", encoding="utf-8")

    out = asyncio.run(
        grep_files_handler(
            {
                "pattern": "alpha",
                "case_insensitive": True,
            },
            SimpleNamespace(cwd=tmp_path),
        )
    )

    assert "a.txt:1:Alpha" in out
    assert "b.txt:2:ALPHA" in out


def test_grep_files_falls_back_when_ripgrep_regex_errors(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("bob.tools.grep_files.shutil.which", lambda name: "rg" if name == "rg" else None)
    monkeypatch.setattr(
        "bob.tools.grep_files.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="regex parse error",
        ),
    )

    (tmp_path / "c.txt").write_text("foobar\n", encoding="utf-8")
    out = asyncio.run(
        grep_files_handler(
            {
                "pattern": r"(?<=foo)bar",
            },
            SimpleNamespace(cwd=tmp_path),
        )
    )

    assert "c.txt:1:foobar" in out
