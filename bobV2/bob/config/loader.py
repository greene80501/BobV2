"""Config loader for bob.

Merges four configuration layers in ascending priority order:
  1. Built-in defaults  (BobConfig())
  2. User-global config (~/.bob/config.toml)
  3. Project config     (walk up from cwd until .bob/config.toml found)
  4. CLI overrides      (dict passed by the caller)
"""

from __future__ import annotations

import json
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

from bob.config.dotenv import load_dotenv_files
from bob.config.schema import BobConfig
from bob.paths import user_config_path


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
    """Return the path to the user-global config file."""
    return user_config_path()


def _load_claude_settings() -> dict[str, Any]:
    """Import MCP servers from Claude Code's settings files.

    Reads ~/.claude/settings.json and ~/.claude/claude_desktop_config.json,
    extracting mcpServers entries and converting them to bob McpServerConfig
    dict format.  Returns a partial BobConfig dict with only mcp_servers set.
    """
    mcp_servers: dict[str, Any] = {}
    claude_home = Path.home() / ".claude"

    settings_candidates = [
        claude_home / "settings.json",
        claude_home / "claude_desktop_config.json",
    ]

    for settings_path in settings_candidates:
        if not settings_path.is_file():
            continue
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        servers_dict = raw.get("mcpServers", {})
        if not isinstance(servers_dict, dict):
            continue

        for srv_name, srv_cfg in servers_dict.items():
            if not isinstance(srv_cfg, dict) or srv_name in mcp_servers:
                continue
            transport = srv_cfg.get("type", "stdio")
            if transport == "stdio" or ("command" in srv_cfg and "type" not in srv_cfg):
                cmd = srv_cfg.get("command", "")
                entry: dict[str, Any] = {
                    "type": "stdio",
                    "command": [cmd] if isinstance(cmd, str) else list(cmd),
                    "args": list(srv_cfg.get("args", [])),
                    "env": dict(srv_cfg.get("env", {})),
                }
            elif transport == "sse":
                entry = {
                    "type": "sse",
                    "url": srv_cfg.get("url", ""),
                    "headers": dict(srv_cfg.get("headers", {})),
                    "env": dict(srv_cfg.get("env", {})),
                }
            elif transport in ("http", "streamable_http"):
                entry = {
                    "type": "http",
                    "url": srv_cfg.get("url", ""),
                    "headers": dict(srv_cfg.get("headers", {})),
                    "env": dict(srv_cfg.get("env", {})),
                }
            else:
                continue
            mcp_servers[srv_name] = entry

    if not mcp_servers:
        return {}
    return {"mcp_servers": mcp_servers}


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

    # Bootstrap environment variables from .env files before resolving config.
    load_dotenv_files(cwd)

    # Layer 1: built-in defaults
    merged: dict[str, Any] = BobConfig().model_dump()

    # Layer 2: user-global config
    user_cfg = _load_toml(_user_config_path())
    if user_cfg:
        merged = _deep_merge(merged, user_cfg)

    # Layer 2.5: import MCP servers from Claude Code settings (if enabled)
    merged_config_so_far = BobConfig.model_validate(merged)
    if merged_config_so_far.import_claude_mcp:
        claude_cfg = _load_claude_settings()
        if claude_cfg:
            merged = _deep_merge(merged, claude_cfg)

    # Layer 3: project config (walk up from cwd)
    project_cfg = _find_project_config(cwd)
    if project_cfg:
        merged = _deep_merge(merged, project_cfg)

    # Layer 4: CLI overrides
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    # Validate and coerce the merged dict through the Pydantic model.
    return BobConfig.model_validate(merged)
