from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional
from bob.protocol.items import SkillMetadata, SkillsListEntry


class SkillsManager:
    """Discovers and caches skills from user and repo scopes."""

    def __init__(self, bob_home: Path):
        self._bob_home = bob_home
        # Cache keyed by resolved directory path string
        self._cache: dict[str, list[SkillMetadata]] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(
        self,
        cwd: Optional[Path] = None,
        force_reload: bool = False,
    ) -> list[SkillsListEntry]:
        """Discover skills from all known scopes.

        Searches:
        1. ``~/.bob/skills/``  (user scope)
        2. ``<cwd>/.bob/skills/``  (repo scope)

        Returns a list of :class:`SkillsListEntry` — one per directory that
        contained at least one directory with a ``skill.toml``.
        """
        search_dirs: list[tuple[str, Path]] = [
            ("user", self._bob_home / "skills"),
        ]
        if cwd is not None:
            search_dirs.append(("repo", cwd / ".bob" / "skills"))

        entries: list[SkillsListEntry] = []
        for scope, directory in search_dirs:
            if not directory.exists():
                continue
            skills = self._load_from_dir(directory, scope, force_reload)
            if skills:
                entries.append(SkillsListEntry(cwd=directory, skills=skills))

        return entries

    def _load_from_dir(
        self,
        directory: Path,
        scope: str,
        force_reload: bool,
    ) -> list[SkillMetadata]:
        cache_key = str(directory.resolve())
        if not force_reload and cache_key in self._cache:
            return self._cache[cache_key]

        skills: list[SkillMetadata] = []
        try:
            for entry in sorted(directory.iterdir()):
                if not entry.is_dir():
                    continue
                skill_toml = entry / "skill.toml"
                if not skill_toml.exists():
                    continue
                metadata = self._parse_skill_toml(skill_toml, entry, scope)
                if metadata is not None:
                    skills.append(metadata)
        except PermissionError:
            pass

        self._cache[cache_key] = skills
        return skills

    @staticmethod
    def _parse_skill_toml(
        toml_path: Path,
        skill_dir: Path,
        scope: str,
    ) -> Optional[SkillMetadata]:
        try:
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                try:
                    import tomllib  # type: ignore[no-redef]
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]

            with open(toml_path, "rb") as fh:
                data = tomllib.load(fh)

            return SkillMetadata(
                name=data.get("name", skill_dir.name),
                description=data.get("description", ""),
                short_description=data.get("short_description"),
                path=skill_dir,
                scope=scope,
                enabled=data.get("enabled", True),
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate(self, directory: Optional[Path] = None) -> None:
        """Invalidate the cache, optionally for a specific directory only."""
        if directory is None:
            self._cache.clear()
        else:
            self._cache.pop(str(directory.resolve()), None)

    def list_all(self, cwd: Optional[Path] = None) -> list[SkillMetadata]:
        """Convenience: return a flat list of all discovered skills."""
        all_skills: list[SkillMetadata] = []
        for entry in self.discover(cwd=cwd):
            all_skills.extend(entry.skills)
        return all_skills

    def find(self, name: str, cwd: Optional[Path] = None) -> Optional[SkillMetadata]:
        """Find a skill by name (case-insensitive)."""
        name_lower = name.lower()
        for skill in self.list_all(cwd=cwd):
            if skill.name.lower() == name_lower:
                return skill
        return None
