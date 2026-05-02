from __future__ import annotations

import os
from pathlib import Path


def _candidate_env_files(cwd: Path) -> list[Path]:
    """Return candidate .env files in load order (low -> high priority).

    Order:
    1) ~/.bob/.env
    2) nearest project .env found by walking cwd upward
    """
    candidates: list[Path] = []
    user_env = Path.home() / ".bob" / ".env"
    if user_env.is_file():
        candidates.append(user_env)

    current = cwd.resolve()
    while True:
        env_path = current / ".env"
        if env_path.is_file():
            candidates.append(env_path)
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return candidates


def load_dotenv_files(cwd: Path, *, override: bool = False) -> list[Path]:
    """Load .env files if python-dotenv is available.

    Returns the list of .env file paths that were loaded.
    """
    try:
        from dotenv import dotenv_values
    except Exception:
        return []

    loaded: list[Path] = []
    for env_path in _candidate_env_files(cwd):
        loaded_any = False
        for key, value in dotenv_values(env_path).items():
            # Treat blank values from lower-priority env files as placeholders so
            # later project-level files can still supply real credentials.
            current = os.environ.get(key)
            if override or current is None or current == "":
                os.environ[key] = "" if value is None else str(value)
                loaded_any = True
        if loaded_any:
            loaded.append(env_path)
    return loaded
