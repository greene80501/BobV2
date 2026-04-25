from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional


_EXCLUDE_NAMES = frozenset([
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".env", "dist", "build", ".next", ".nuxt", "target",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
])


class IsolatedWorkspace:
    """Temp-dir workspace for a single swarm agent.

    Files from the real project are copied in at construction time.
    The agent writes exclusively to this dir. After completion,
    generate_patch() diffs the workspace against the originals.
    """

    def __init__(self, real_cwd: Path, files_to_seed: Optional[list[str]] = None):
        self.real_cwd = real_cwd.resolve()
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="bob_swarm_"))
        self._seeded_files: set[str] = set()

        if files_to_seed:
            self._seed_selective(files_to_seed)
        else:
            self._seed_full()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_rel_path(rel: str) -> Path | None:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        return rel_path

    def _seed_selective(self, rel_paths: list[str]) -> None:
        for rel in rel_paths:
            rel_path = self._safe_rel_path(rel)
            if rel_path is None:
                continue
            src = self.real_cwd / rel_path
            if not src.exists():
                continue
            dst = self.workspace_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(src, dst)
                self._seeded_files.add(rel_path.as_posix())
            elif src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(*_EXCLUDE_NAMES))
                self._record_workspace_files(dst)

    def _seed_full(self) -> None:
        shutil.copytree(
            self.real_cwd,
            self.workspace_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*_EXCLUDE_NAMES),
        )
        self._record_workspace_files(self.workspace_dir)

    def _record_workspace_files(self, root: Path) -> None:
        if root.is_file():
            try:
                self._seeded_files.add(root.relative_to(self.workspace_dir).as_posix())
            except ValueError:
                pass
            return
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _EXCLUDE_NAMES)
            for fname in files:
                try:
                    rel = (Path(dirpath) / fname).relative_to(self.workspace_dir).as_posix()
                except ValueError:
                    continue
                self._seeded_files.add(rel)

    @staticmethod
    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_text_if_safe(path: Path) -> str | None:
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in raw:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Diff generation
    # ------------------------------------------------------------------

    def generate_patch(self) -> tuple[str, list[str]]:
        """Return (unified_diff_text, [modified_rel_paths])."""
        diff_chunks: list[str] = []
        changed: list[str] = []

        for root, dirs, files in os.walk(self.workspace_dir):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _EXCLUDE_NAMES)
            for fname in sorted(files):
                ws_file = Path(root) / fname
                try:
                    rel_posix = ws_file.relative_to(self.workspace_dir).as_posix()
                except ValueError:
                    continue

                orig_file = self.real_cwd / rel_posix

                ws_lines = ws_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                orig_lines = (
                    orig_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                    if orig_file.exists()
                    else []
                )

                if ws_lines == orig_lines:
                    continue

                diff = list(difflib.unified_diff(
                    orig_lines, ws_lines,
                    fromfile=f"a/{rel_posix}",
                    tofile=f"b/{rel_posix}",
                    lineterm="",
                ))
                if diff:
                    diff_chunks.append("\n".join(diff))
                    changed.append(rel_posix)

        return "\n\n".join(diff_chunks), changed

    def generate_change_bundle(self, *, agent_id: str, role: str) -> tuple[dict[str, Any], list[str]]:
        """Return a conflict-checkable text change bundle for UI application."""
        files: list[dict[str, Any]] = []
        changed: list[str] = []
        candidates: set[str] = set(self._seeded_files)

        for root, dirs, names in os.walk(self.workspace_dir):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _EXCLUDE_NAMES)
            for fname in names:
                try:
                    candidates.add((Path(root) / fname).relative_to(self.workspace_dir).as_posix())
                except ValueError:
                    continue

        for rel in sorted(candidates):
            ws_file = self.workspace_dir / rel
            orig_file = self.real_cwd / rel

            orig_text = self._read_text_if_safe(orig_file) if orig_file.exists() else None
            ws_text = self._read_text_if_safe(ws_file) if ws_file.exists() else None
            if orig_text == ws_text:
                continue

            if orig_file.exists() and orig_text is None:
                files.append({
                    "path": rel,
                    "operation": "unsupported_binary",
                    "reason": "original file is binary or unreadable",
                })
                continue
            if ws_file.exists() and ws_text is None:
                files.append({
                    "path": rel,
                    "operation": "unsupported_binary",
                    "reason": "workspace file is binary or unreadable",
                })
                continue

            if ws_file.exists():
                operation = "write"
                new_text = ws_text or ""
            else:
                operation = "delete"
                new_text = None

            files.append({
                "path": rel,
                "operation": operation,
                "old_sha256": self._sha256_text(orig_text) if orig_text is not None else None,
                "new_sha256": self._sha256_text(new_text) if new_text is not None else None,
                "content": new_text,
                "agent_id": agent_id,
                "role": role,
            })
            changed.append(rel)

        return {
            "format": "bob_swarm_bundle_v1",
            "agent_id": agent_id,
            "role": role,
            "workspace_dir": str(self.workspace_dir),
            "files": files,
        }, changed

    @staticmethod
    def encode_bundles(bundles: list[dict[str, Any]]) -> str:
        return json.dumps({
            "format": "bob_swarm_bundle_v1",
            "bundles": bundles,
        }, ensure_ascii=False, indent=2)

    def cleanup(self) -> None:
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def __str__(self) -> str:
        return str(self.workspace_dir)

    def __repr__(self) -> str:
        return f"IsolatedWorkspace({self.workspace_dir})"
