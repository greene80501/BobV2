from __future__ import annotations

from pathlib import Path

import bob.llm.catalog as catalog_module
from bob.app_server.server import AppServer
from bob.paths import bob_home, bob_home_path, user_config_path, user_env_path


def test_bob_home_helpers_honor_env_override(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    custom_home = tmp_path / "custom-bob"

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("BOB_HOME", str(custom_home))

    assert bob_home() == custom_home
    assert bob_home_path("logs", "actions.log") == custom_home / "logs" / "actions.log"
    assert user_config_path() == custom_home / "config.toml"
    assert user_env_path() == custom_home / ".env"


def test_app_server_uses_bob_home_paths(tmp_path: Path, monkeypatch) -> None:
    custom_home = tmp_path / "custom-bob"
    monkeypatch.setenv("BOB_HOME", str(custom_home))

    server = AppServer()

    assert server.event_bus._db_path == custom_home / "app_events.sqlite"
    assert server.task_runtime.store.db_path == custom_home / "tasks_runtime.sqlite"


def test_get_catalog_refreshes_when_bob_home_changes(tmp_path: Path, monkeypatch) -> None:
    original = catalog_module._catalog
    catalog_module._catalog = None
    try:
        first_home = tmp_path / "bob-one"
        second_home = tmp_path / "bob-two"

        monkeypatch.setenv("BOB_HOME", str(first_home))
        first = catalog_module.get_catalog()

        monkeypatch.setenv("BOB_HOME", str(second_home))
        second = catalog_module.get_catalog()

        assert first.db_path == first_home / "llm_database.db"
        assert second.db_path == second_home / "llm_database.db"
        assert first is not second
    finally:
        catalog_module._catalog = original
