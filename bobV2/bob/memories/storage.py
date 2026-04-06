from __future__ import annotations
import shutil
from pathlib import Path
from typing import Optional


class MemoryStorage:
    """Manages the memories directory and consolidated memory file."""

    _RAW_MEMORIES_FILENAME = "raw_memories.md"
    _SUMMARIES_SUBDIR = "rollout_summaries"

    def __init__(self, memories_dir: Path):
        self._dir = memories_dir
        self._summaries_dir = memories_dir / self._SUMMARIES_SUBDIR
        self._raw_memories_file = memories_dir / self._RAW_MEMORIES_FILENAME

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """Create the memories directory structure if it does not exist."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._summaries_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def load_memories(self, max_tokens: int = 5000) -> Optional[str]:
        """Load the consolidated memory file, truncated to *max_tokens* (approx).

        Returns ``None`` if no memories have been written yet.
        """
        if not self._raw_memories_file.exists():
            return None
        try:
            content = self._raw_memories_file.read_text(encoding="utf-8")
        except OSError:
            return None
        if not content.strip():
            return None
        # Rough truncation: 4 characters ≈ 1 token
        char_limit = max_tokens * 4
        if len(content) > char_limit:
            content = content[:char_limit] + "\n\n... (truncated)"
        return content

    def read_all_summaries(self) -> list[str]:
        """Return the text of every per-session summary file."""
        summaries: list[str] = []
        if not self._summaries_dir.exists():
            return summaries
        for summary_path in sorted(self._summaries_dir.glob("*.md")):
            try:
                text = summary_path.read_text(encoding="utf-8")
                if text.strip():
                    summaries.append(text)
            except OSError:
                pass
        return summaries

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write_summary(self, session_id: str, summary: str) -> None:
        """Persist a per-session memory summary."""
        self._summaries_dir.mkdir(parents=True, exist_ok=True)
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        path = self._summaries_dir / f"{safe_id}.md"
        path.write_text(summary, encoding="utf-8")

    def write_consolidated(self, content: str) -> None:
        """Write the consolidated (phase-2) memory document."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._raw_memories_file.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def drop_all(self) -> None:
        """Delete all persisted memory files and recreate the directory skeleton."""
        if self._summaries_dir.exists():
            shutil.rmtree(self._summaries_dir, ignore_errors=True)
        if self._raw_memories_file.exists():
            try:
                self._raw_memories_file.unlink()
            except OSError:
                pass
        self.setup()

    def drop_summary(self, session_id: str) -> bool:
        """Remove a single per-session summary. Returns True if it existed."""
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        path = self._summaries_dir / f"{safe_id}.md"
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError:
                pass
        return False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def memories_path(self) -> Path:
        return self._raw_memories_file

    @property
    def summaries_dir(self) -> Path:
        return self._summaries_dir

    def summary_count(self) -> int:
        if not self._summaries_dir.exists():
            return 0
        return sum(1 for _ in self._summaries_dir.glob("*.md"))
