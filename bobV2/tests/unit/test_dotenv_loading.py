from __future__ import annotations

from pathlib import Path

from bob.config.dotenv import _candidate_env_files
from bob.config.loader import load_config


def test_candidate_env_files_prefers_user_then_project(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    project = tmp_path / "workspace" / "repo"
    nested = project / "src" / "pkg"
    (fake_home / ".bob").mkdir(parents=True)
    nested.mkdir(parents=True)

    user_env = fake_home / ".bob" / ".env"
    project_env = project / ".env"
    user_env.write_text("OPENAI_API_KEY=user-key\n", encoding="utf-8")
    project_env.write_text("OPENAI_API_KEY=project-key\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)

    files = _candidate_env_files(nested)

    assert files == [user_env, project_env]


def test_load_config_uses_project_dotenv_for_provider_key(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    project = tmp_path / "repo"
    (fake_home / ".bob").mkdir(parents=True)
    project.mkdir()
    (project / ".env").write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    # Ensure no ambient key leaks into this test.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    cfg = load_config(cwd=project)

    # The key is read from env at runtime resolution; this validates .env loading happened.
    from bob.llm.compatibility import resolve_provider_auth

    auth = resolve_provider_auth("gpt-5.1-codex-mini", cfg)
    assert auth.api_key == "from-dotenv"


def test_project_dotenv_overrides_blank_user_value(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    project = tmp_path / "repo"
    (fake_home / ".bob").mkdir(parents=True)
    project.mkdir()

    (fake_home / ".bob" / ".env").write_text("KIMI_API_KEY=\n", encoding="utf-8")
    (project / ".env").write_text("KIMI_API_KEY=from-project\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    cfg = load_config(cwd=project)

    from bob.llm.compatibility import resolve_provider_auth

    auth = resolve_provider_auth("kimi/kimi-for-coding", cfg)
    assert auth.api_key == "from-project"
