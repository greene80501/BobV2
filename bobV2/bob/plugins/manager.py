from __future__ import annotations
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class PluginInfo:
    """Metadata describing an installed plugin."""

    name: str
    version: str
    description: str
    path: Path
    enabled: bool = True


@dataclass
class ClaudeCodeMcpConfig:
    """An MCP server config extracted from a Claude Code plugin's .mcp.json."""
    server_name: str
    plugin_name: str
    transport: str  # "stdio" | "sse" | "http"
    command: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ClaudeCodeSkillInfo:
    """A skill loaded from a Claude Code plugin's SKILL.md."""
    name: str
    description: str
    short_description: str
    plugin_name: str
    plugin_path: Path
    user_invocable: bool = False
    allowed_tools: list[str] = field(default_factory=list)
    content_file: str = "SKILL.md"


class PluginsManager:
    """Manages bob plugins stored in a plugins directory.

    Plugin layout::

        <plugins_dir>/
            my-plugin/
                plugin.toml    ← required; declares name/version/description
                __init__.py    ← optional Python entry point
    """

    _MANIFEST_FILENAME = "plugin.toml"
    _CLAUDE_MANIFEST_FILENAME = Path(".claude-plugin") / "plugin.json"
    _CODEX_MANIFEST_FILENAME = Path(".codex-plugin") / "plugin.json"

    def __init__(self, plugins_dir: Path):
        self._dir = plugins_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[PluginInfo]:
        """Return metadata for all installed plugins, sorted by name."""
        plugins: list[PluginInfo] = []
        if not self._dir.exists():
            return plugins

        for plugin_dir in sorted(self._dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            info = self._parse_plugin_dir(plugin_dir)
            if info is not None:
                plugins.append(info)

        return plugins

    def get_plugin(self, name: str) -> Optional[PluginInfo]:
        """Return info for a single plugin by name, or None."""
        for plugin in self.list_plugins():
            if plugin.name == name:
                return plugin
        return None

    # ------------------------------------------------------------------
    # Installation / removal
    # ------------------------------------------------------------------

    def install_from_path(self, source: Path) -> Optional[PluginInfo]:
        """Install a plugin by copying a local directory into the plugins dir.

        The source directory must contain a supported plugin manifest.
        Returns the :class:`PluginInfo` on success, or ``None`` on failure.
        """
        info = self._parse_plugin_dir(source)
        if info is None:
            return None

        dest = self._dir / source.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.copytree(source, dest)
        except OSError:
            return None

        return self._parse_plugin_dir(dest)

    def uninstall(self, name: str) -> bool:
        """Uninstall a plugin by name. Returns True if the plugin existed."""
        for plugin_dir in self._dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            info = self._parse_plugin_dir(plugin_dir)
            if info and info.name == name:
                shutil.rmtree(plugin_dir, ignore_errors=True)
                return True
        return False

    # ------------------------------------------------------------------
    # Plugin loading (Python entry points)
    # ------------------------------------------------------------------

    def load_plugin(self, name: str) -> bool:
        """Import a plugin's Python package, adding it to sys.path if needed.

        Returns True if the plugin was found and loaded successfully.
        """
        info = self.get_plugin(name)
        if info is None:
            return False
        plugin_dir_str = str(info.path.parent)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
        try:
            __import__(info.path.name)
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_manifest(manifest: Path, plugin_dir: Path) -> Optional[PluginInfo]:
        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                try:
                    import tomllib  # type: ignore[no-redef]
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]

            with open(manifest, "rb") as fh:
                data = tomllib.load(fh)

            return PluginInfo(
                name=data.get("name", plugin_dir.name),
                version=data.get("version", "0.0.0"),
                description=data.get("description", ""),
                path=plugin_dir,
                enabled=data.get("enabled", True),
            )
        except Exception:
            return None

    @staticmethod
    def _parse_json_manifest(manifest: Path, plugin_dir: Path) -> Optional[PluginInfo]:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            interface = data.get("interface", {}) if isinstance(data.get("interface"), dict) else {}
            return PluginInfo(
                name=data.get("name", plugin_dir.name),
                version=data.get("version", "0.0.0"),
                description=(
                    data.get("description")
                    or interface.get("shortDescription")
                    or interface.get("longDescription")
                    or ""
                ),
                path=plugin_dir,
                enabled=bool(data.get("enabled", True)),
            )
        except Exception:
            return None

    def _parse_plugin_dir(self, plugin_dir: Path) -> Optional[PluginInfo]:
        manifest = plugin_dir / self._MANIFEST_FILENAME
        if manifest.exists():
            info = self._parse_manifest(manifest, plugin_dir)
            if info is not None:
                return info

        for rel_path in (self._CLAUDE_MANIFEST_FILENAME, self._CODEX_MANIFEST_FILENAME):
            json_manifest = plugin_dir / rel_path
            if json_manifest.exists():
                info = self._parse_json_manifest(json_manifest, plugin_dir)
                if info is not None:
                    return info
        return None

    # ------------------------------------------------------------------
    # Remote marketplace
    # ------------------------------------------------------------------

    DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/bob-plugins/registry/main/registry.json"

    def fetch_registry(self, url: str = "") -> list[dict]:
        """Download and return the plugin registry as a list of plugin dicts.

        Each entry has at minimum: name, version, description, download_url.
        Returns empty list on failure.
        """
        registry_url = url or self.DEFAULT_REGISTRY_URL
        try:
            import urllib.request
            with urllib.request.urlopen(registry_url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("plugins", [])
        except Exception:
            pass
        return []

    def search_registry(self, query: str, url: str = "") -> list[dict]:
        """Search the remote registry for plugins matching *query*."""
        all_plugins = self.fetch_registry(url)
        if not query:
            return all_plugins
        q = query.lower()
        return [
            p for p in all_plugins
            if q in p.get("name", "").lower()
            or q in p.get("description", "").lower()
            or q in " ".join(p.get("keywords", [])).lower()
        ]

    def install_from_url(self, url: str) -> Optional[PluginInfo]:
        """Download a plugin zip from *url* and install it.

        The zip must contain a top-level directory with a plugin.toml inside.
        Returns PluginInfo on success, None on failure.
        """
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as resp:
                raw = resp.read()
        except Exception:
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                if not names:
                    return None
                # Determine the top-level directory in the zip
                root = names[0].split("/")[0]
                with tempfile.TemporaryDirectory() as tmpdir:
                    zf.extractall(tmpdir)
                    extracted = Path(tmpdir) / root
                    if not extracted.is_dir():
                        extracted = Path(tmpdir)
                    return self.install_from_path(extracted)
        except Exception:
            return None

    def install_from_registry(self, name: str, registry_url: str = "") -> Optional[PluginInfo]:
        """Find *name* in the registry and install it."""
        plugins = self.fetch_registry(registry_url)
        for p in plugins:
            if p.get("name", "").lower() == name.lower():
                download_url = p.get("download_url", "")
                if download_url:
                    return self.install_from_url(download_url)
        return None

    @property
    def plugins_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Claude Code plugin support
    # ------------------------------------------------------------------

    @staticmethod
    def _substitute_plugin_vars(text: str, plugin_root: Path) -> str:
        """Replace plugin-root shorthands and ${ENV_VAR} placeholders in text."""
        text = text.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
        text = text.replace("${BOB_PLUGIN_ROOT}", str(plugin_root))
        text = text.replace("${PLUGIN_ROOT}", str(plugin_root))

        env = {**os.environ, "BOB_PYTHON": sys.executable}

        def _replace(m: re.Match) -> str:
            return env.get(m.group(1), m.group(0))

        return re.sub(r"\$\{([^}]+)\}", _replace, text)

    @staticmethod
    def _substitute_vars_in_dict(d: Any, plugin_root: Path) -> Any:
        if isinstance(d, str):
            return PluginsManager._substitute_plugin_vars(d, plugin_root)
        if isinstance(d, dict):
            return {
                k: PluginsManager._substitute_vars_in_dict(v, plugin_root)
                for k, v in d.items()
            }
        if isinstance(d, list):
            return [PluginsManager._substitute_vars_in_dict(i, plugin_root) for i in d]
        return d

    @staticmethod
    def _parse_mcp_json(
        mcp_json_path: Path,
        plugin_name: str,
    ) -> list[ClaudeCodeMcpConfig]:
        """Parse a .mcp.json file and return a list of MCP server configs.

        Supports two schema variants:
          Schema A: {"server": {"command": ..., "args": ...}}
          Schema B: {"mcpServers": {"name": {"command": ...}}}
        """
        try:
            raw = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        plugin_root = mcp_json_path.parent
        configs: list[ClaudeCodeMcpConfig] = []

        def _parse_server(server_name: str, srv: dict) -> Optional[ClaudeCodeMcpConfig]:
            srv = PluginsManager._substitute_vars_in_dict(srv, plugin_root)
            transport = srv.get("type", "stdio")
            if transport == "stdio" or ("command" in srv and "type" not in srv):
                return ClaudeCodeMcpConfig(
                    server_name=server_name,
                    plugin_name=plugin_name,
                    transport="stdio",
                    command=[srv["command"]] if isinstance(srv.get("command"), str) else list(srv.get("command", [])),
                    args=list(srv.get("args", [])),
                    env=dict(srv.get("env", {})),
                )
            elif transport == "sse":
                return ClaudeCodeMcpConfig(
                    server_name=server_name,
                    plugin_name=plugin_name,
                    transport="sse",
                    url=srv.get("url", ""),
                    headers=dict(srv.get("headers", {})),
                    env=dict(srv.get("env", {})),
                )
            elif transport in ("http", "streamable_http"):
                return ClaudeCodeMcpConfig(
                    server_name=server_name,
                    plugin_name=plugin_name,
                    transport="http",
                    url=srv.get("url", ""),
                    headers=dict(srv.get("headers", {})),
                    env=dict(srv.get("env", {})),
                )
            return None

        # Schema A: single server at top level
        if "server" in raw and isinstance(raw["server"], dict):
            cfg = _parse_server(plugin_name, raw["server"])
            if cfg:
                configs.append(cfg)
        # Schema B: named servers dict
        if "mcpServers" in raw and isinstance(raw["mcpServers"], dict):
            for srv_name, srv_cfg in raw["mcpServers"].items():
                if isinstance(srv_cfg, dict):
                    cfg = _parse_server(srv_name, srv_cfg)
                    if cfg:
                        configs.append(cfg)
        return configs

    @staticmethod
    def _parse_skill_md(
        skill_md_path: Path,
        plugin_name: str,
    ) -> Optional[ClaudeCodeSkillInfo]:
        """Parse a SKILL.md file with YAML frontmatter."""
        try:
            import yaml
        except ImportError:
            return None
        try:
            text = skill_md_path.read_text(encoding="utf-8")
            fm: dict = {}
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    fm_text = text[3:end].strip()
                    fm = yaml.safe_load(fm_text) or {}
            return ClaudeCodeSkillInfo(
                name=fm.get("name", skill_md_path.parent.name),
                description=fm.get("description", ""),
                short_description=fm.get("short-description") or fm.get("short_description", ""),
                plugin_name=plugin_name,
                plugin_path=skill_md_path.parent,
                user_invocable=bool(fm.get("user-invocable", fm.get("user_invocable", False))),
                allowed_tools=list(fm.get("allowed-tools", fm.get("allowed_tools", []))),
                content_file="SKILL.md",
            )
        except Exception:
            return None

    @classmethod
    def _load_bundle_from_plugin_dir(
        cls,
        plugin_dir: Path,
        plugin_name: str,
    ) -> tuple[list[ClaudeCodeMcpConfig], list[ClaudeCodeSkillInfo]]:
        mcp_configs: list[ClaudeCodeMcpConfig] = []
        skill_infos: list[ClaudeCodeSkillInfo] = []

        mcp_json = plugin_dir / ".mcp.json"
        if mcp_json.exists():
            mcp_configs.extend(cls._parse_mcp_json(mcp_json, plugin_name))

        embedded_manifests = [
            plugin_dir / cls._CLAUDE_MANIFEST_FILENAME,
            plugin_dir / cls._CODEX_MANIFEST_FILENAME,
        ]
        for embedded_plugin_json in embedded_manifests:
            if not embedded_plugin_json.exists():
                continue
            try:
                pj = json.loads(embedded_plugin_json.read_text(encoding="utf-8"))
                if "mcpServer" not in pj:
                    continue
                srv = cls._substitute_vars_in_dict(pj["mcpServer"], plugin_dir)
                transport = srv.get("type", "stdio")
                if transport == "stdio" or "command" in srv:
                    cmd = srv.get("command", "")
                    mcp_configs.append(ClaudeCodeMcpConfig(
                        server_name=plugin_name,
                        plugin_name=plugin_name,
                        transport="stdio",
                        command=[cmd] if isinstance(cmd, str) else list(cmd),
                        args=list(srv.get("args", [])),
                        env=dict(srv.get("env", {})),
                    ))
                elif transport == "sse":
                    mcp_configs.append(ClaudeCodeMcpConfig(
                        server_name=plugin_name,
                        plugin_name=plugin_name,
                        transport="sse",
                        url=srv.get("url", ""),
                        headers=dict(srv.get("headers", {})),
                        env=dict(srv.get("env", {})),
                    ))
                elif transport in ("http", "streamable_http"):
                    mcp_configs.append(ClaudeCodeMcpConfig(
                        server_name=plugin_name,
                        plugin_name=plugin_name,
                        transport="http",
                        url=srv.get("url", ""),
                        headers=dict(srv.get("headers", {})),
                        env=dict(srv.get("env", {})),
                    ))
            except Exception:
                pass

        skill_md_candidates = [plugin_dir / "SKILL.md"]
        skills_subdir = plugin_dir / "skills"
        if skills_subdir.is_dir():
            skill_md_candidates.extend(skills_subdir.glob("*/SKILL.md"))
        for skill_md in skill_md_candidates:
            if skill_md.exists():
                info = cls._parse_skill_md(skill_md, plugin_name)
                if info:
                    skill_infos.append(info)

        return mcp_configs, skill_infos

    @classmethod
    def load_plugin_bundles_from_roots(
        cls,
        plugin_roots: list[Path],
    ) -> tuple[list[ClaudeCodeMcpConfig], list[ClaudeCodeSkillInfo]]:
        """Load MCP and skill metadata from Bob-owned local plugin roots."""
        mcp_configs: list[ClaudeCodeMcpConfig] = []
        skill_infos: list[ClaudeCodeSkillInfo] = []

        for plugin_root in plugin_roots:
            if not plugin_root.exists():
                continue
            for plugin_dir in sorted(plugin_root.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                info = cls(plugin_root)._parse_plugin_dir(plugin_dir)
                if info is None:
                    continue
                cfgs, skills = cls._load_bundle_from_plugin_dir(plugin_dir, info.name)
                mcp_configs.extend(cfgs)
                skill_infos.extend(skills)

        return mcp_configs, skill_infos

    def load_claude_code_plugins(
        self,
        claude_plugins_dir: Optional[Path] = None,
    ) -> tuple[list[ClaudeCodeMcpConfig], list[ClaudeCodeSkillInfo]]:
        """Discover and load all Claude Code plugins from claude_plugins_dir.

        Default: ~/.claude/plugins/
        Returns (mcp_configs, skill_infos).
        """
        if claude_plugins_dir is None:
            claude_plugins_dir = Path.home() / ".claude" / "plugins"

        mcp_configs: list[ClaudeCodeMcpConfig] = []
        skill_infos: list[ClaudeCodeSkillInfo] = []

        if not claude_plugins_dir.exists():
            return mcp_configs, skill_infos

        for plugin_dir in sorted(claude_plugins_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            plugin_name = plugin_dir.name
            cfgs, skills = self._load_bundle_from_plugin_dir(plugin_dir, plugin_name)
            mcp_configs.extend(cfgs)
            skill_infos.extend(skills)

        return mcp_configs, skill_infos
