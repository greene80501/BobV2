from __future__ import annotations
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PluginInfo:
    """Metadata describing an installed plugin."""

    name: str
    version: str
    description: str
    path: Path
    enabled: bool = True


class PluginsManager:
    """Manages bob plugins stored in a plugins directory.

    Plugin layout::

        <plugins_dir>/
            my-plugin/
                plugin.toml    ← required; declares name/version/description
                __init__.py    ← optional Python entry point
    """

    _MANIFEST_FILENAME = "plugin.toml"

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
            manifest = plugin_dir / self._MANIFEST_FILENAME
            if not manifest.exists():
                continue
            info = self._parse_manifest(manifest, plugin_dir)
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

        The source directory must contain a ``plugin.toml``.
        Returns the :class:`PluginInfo` on success, or ``None`` on failure.
        """
        manifest = source / self._MANIFEST_FILENAME
        if not manifest.exists():
            return None

        info = self._parse_manifest(manifest, source)
        if info is None:
            return None

        dest = self._dir / source.name
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.copytree(source, dest)
        except OSError:
            return None

        return self._parse_manifest(dest / self._MANIFEST_FILENAME, dest)

    def uninstall(self, name: str) -> bool:
        """Uninstall a plugin by name. Returns True if the plugin existed."""
        for plugin_dir in self._dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest = plugin_dir / self._MANIFEST_FILENAME
            if not manifest.exists():
                continue
            info = self._parse_manifest(manifest, plugin_dir)
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

    @property
    def plugins_dir(self) -> Path:
        return self._dir
