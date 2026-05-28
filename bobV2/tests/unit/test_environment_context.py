from __future__ import annotations

from pathlib import Path

from bob.core.environment_context import EnvironmentContext


def test_environment_context_lists_all_top_level_items(tmp_path: Path) -> None:
    (tmp_path / "bob").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".env").write_text("KEY=value", encoding="utf-8")
    (tmp_path / "README.md").write_text("# test", encoding="utf-8")

    ctx = EnvironmentContext.build(tmp_path)
    text = ctx.to_prompt_text()

    assert "Startup workspace snapshot:" in text
    assert f"- cwd: {tmp_path}" in text
    assert "  - bob/" in text
    assert "  - tests/" in text
    assert "  - .env" in text
    assert "  - README.md" in text
    assert "authoritative starting state" in text
    assert "Do not probe parent directories with `..`" in text
