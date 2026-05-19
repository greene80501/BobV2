from __future__ import annotations

import os
from pathlib import Path


def bob_home() -> Path:
    """Return Bob's user data directory."""
    raw = os.environ.get("BOB_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".bob"


def bob_home_path(*parts: str) -> Path:
    """Return a path inside Bob's user data directory."""
    path = bob_home()
    for part in parts:
        path /= part
    return path


def user_config_path() -> Path:
    """Return the path to the user-global config file."""
    return bob_home_path("config.toml")


def user_env_path() -> Path:
    """Return the path to the user-global .env file."""
    return bob_home_path(".env")
