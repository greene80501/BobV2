"""Config loader for bob.

Merges four configuration layers in ascending priority order:
  1. Built-in defaults  (BobConfig())
  2. User-global config (~/.bob/config.toml)
  3. Project config     (walk up from cwd until .bob/config.toml found)
  4. CLI overrides      (dict passed by the caller)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

# tomllib is stdlib in Python 3.11+; fall back to tomli for older versions.
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError as exc:
            raise ImportError(
                "Python < 3.11 requires the 'tomli' package: pip install tomli"
            ) from exc

from bob.config.schema import BobConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file and return its contents as a plain dict.

    Returns an empty dict if the file does not exist.
    """
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*.

    - dict values are merged recursively.
    - All other values are replaced by the override.
    - Neither input dict is mutated; a new dict is returned.
    """
    result: dict[str, Any] = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _find_project_config(cwd: Path) -> dict[str, Any]:
    """Walk *cwd* upward looking for a .bob/config.toml file.

    Stops at the filesystem root or when a home directory boundary is crossed.
    Returns the first one found, or an empty dict if none exists.
    """
    home = Path.home()
    current = cwd.resolve()

    while True:
        candidate = current / ".bob" / "config.toml"
        if candidate.is_file():
            return _load_toml(candidate)

        parent = current.parent
        # Stop at root or if we have gone above the home directory
        if parent == current:
            break
        # Do not crawl above the user's home directory
        if current == home:
            break
        current = parent

    return {}


def _user_config_path() -> Path:
    """Return the path to the user-global config file (~/.bob/config.toml)."""
    return Path.home() / ".bob" / "config.toml"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(
    cwd: Optional[Path] = None,
    cli_overrides: Optional[dict[str, Any]] = None,
) -> BobConfig:
    """Load and merge all configuration layers, returning a :class:`BobConfig`.

    Parameters
    ----------
    cwd:
        The working directory from which to start the project-config search.
        Defaults to :func:`os.getcwd`.
    cli_overrides:
        A flat or nested dict of values supplied by the CLI (e.g. ``{"model":
        "gpt-5.1-codex-mini", "sandbox_mode": "read-only"}``).  These have
        the highest priority and override everything else.
    """
    if cwd is None:
        cwd = Path(os.getcwd())
    if cli_overrides is None:
        cli_overrides = {}

    # Layer 1: built-in defaults
    merged: dict[str, Any] = BobConfig().model_dump()

    # Layer 2: user-global config
    user_cfg = _load_toml(_user_config_path())
    if user_cfg:
        merged = _deep_merge(merged, user_cfg)

    # Layer 3: project config (walk up from cwd)
    project_cfg = _find_project_config(cwd)
    if project_cfg:
        merged = _deep_merge(merged, project_cfg)

    # Layer 4: CLI overrides
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    # Validate and coerce the merged dict through the Pydantic model.
    return BobConfig.model_validate(merged)
