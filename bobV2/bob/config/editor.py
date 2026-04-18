from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    return Path(os.environ.get("BOB_HOME", Path.home() / ".bob")) / "config.toml"


def _load_raw() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib  # type: ignore[no-redef]
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _save_raw(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import tomli_w
    except ImportError:
        raise ImportError("tomli_w is required for config editing. Run: pip install tomli_w")
    with open(path, "wb") as fh:
        tomli_w.dump(data, fh)


def _parse_value(s: str) -> Any:
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def set_value(key: str, value: str) -> None:
    """Set a config key (dot-notation) to value."""
    data = _load_raw()
    parts = key.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict):
            raise ValueError(f"Cannot traverse into non-dict at '{part}'")
        current = current.setdefault(part, {})
    current[parts[-1]] = _parse_value(value)
    _save_raw(data)


def get_value(key: str) -> str:
    """Return a config value by dot-notation key, or empty string if unset."""
    data = _load_raw()
    parts = key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return ""
        current = current[part]
    return str(current)


def unset_value(key: str) -> bool:
    """Remove a key from config. Returns True if it existed."""
    data = _load_raw()
    parts = key.split(".")
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    _save_raw(data)
    return True


def list_values() -> list[tuple[str, str]]:
    """Return all (key, value) pairs in dot-notation order."""
    data = _load_raw()
    rows: list[tuple[str, str]] = []

    def _walk(d: dict, prefix: str) -> None:
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _walk(v, full)
            else:
                rows.append((full, str(v)))

    _walk(data, "")
    return rows
