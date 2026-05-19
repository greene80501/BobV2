"""Model catalog backed by LLM-database SQLite.

Reads ~/.bob/llm_database.db (built by the llm-database project).
All lookups return None gracefully when the DB is absent — Bob continues
to work, just without cost estimates.

Build the DB once with:
    cd C:\\Users\\green\\hevay_llm\\LLM-database
    pip install -e .
    python -m llm_database.update   # creates llm_database.db
    # then copy to ~/.bob/llm_database.db
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from bob.paths import bob_home_path

_DEFAULT_DB = bob_home_path("llm_database.db")


class ModelCatalog:
    """Read-only interface to the LLM-database SQLite file."""

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_populated(self) -> bool:
        """True when the DB file exists and contains at least one model."""
        if not self.db_path.exists():
            return False
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT COUNT(*) FROM models").fetchone()
                return (row[0] or 0) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_model(self, model_id: str, provider: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Return full metadata row for *model_id*, or None if not found."""
        if not self.db_path.exists():
            return None
        try:
            with self._conn() as conn:
                q = """
                    SELECT m.*, p.name AS provider, p.display_name AS provider_display,
                           ps.input_price_per_1m, ps.cached_input_price_per_1m,
                           ps.output_price_per_1m, ps.pricing_unit
                    FROM models m
                    JOIN providers p ON m.provider_id = p.id
                    LEFT JOIN pricing_snapshots ps
                        ON m.id = ps.model_id AND ps.effective_until IS NULL
                    WHERE m.model_id = ?
                """
                params: list[Any] = [model_id]
                if provider:
                    q += " AND p.name = ?"
                    params.append(provider)
                q += " LIMIT 1"
                row = conn.execute(q, params).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def get_pricing(self, model_id: str) -> Optional[dict[str, float]]:
        """Return {input_per_1m, cached_per_1m, output_per_1m} in USD, or None."""
        row = self.get_model(model_id)
        if not row:
            return None
        inp = row.get("input_price_per_1m")
        out = row.get("output_price_per_1m")
        if inp is None and out is None:
            return None
        return {
            "input_per_1m":  float(inp or 0.0),
            "cached_per_1m": float(row.get("cached_input_price_per_1m") or 0.0),
            "output_per_1m": float(out or 0.0),
        }

    def get_context_window(self, model_id: str) -> Optional[int]:
        """Return the context window size in tokens, or None."""
        row = self.get_model(model_id)
        return int(row["context_window"]) if row and row.get("context_window") else None

    def list_models(
        self,
        provider: Optional[str] = None,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        """Return all models, optionally filtered by provider and status."""
        if not self.db_path.exists():
            return []
        try:
            with self._conn() as conn:
                q = """
                    SELECT m.model_id, m.display_name, m.family, m.status,
                           m.context_window, m.max_output_tokens,
                           m.input_modalities, m.output_modalities,
                           p.name AS provider, p.display_name AS provider_display,
                           ps.input_price_per_1m, ps.cached_input_price_per_1m,
                           ps.output_price_per_1m
                    FROM models m
                    JOIN providers p ON m.provider_id = p.id
                    LEFT JOIN pricing_snapshots ps
                        ON m.id = ps.model_id AND ps.effective_until IS NULL
                    WHERE 1=1
                """
                params: list[Any] = []
                if provider:
                    q += " AND p.name = ?"
                    params.append(provider)
                if status:
                    q += " AND m.status = ?"
                    params.append(status)
                q += " ORDER BY p.name, m.family, m.model_id"
                rows = conn.execute(q, params).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_providers(self) -> list[dict[str, Any]]:
        """Return all providers with model counts."""
        if not self.db_path.exists():
            return []
        try:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT p.name, p.display_name, p.website_url, p.docs_url,
                           COUNT(m.id) AS model_count
                    FROM providers p
                    LEFT JOIN models m ON p.id = m.provider_id
                    GROUP BY p.id
                    ORDER BY p.name
                """).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def search_models(self, query: str) -> list[dict[str, Any]]:
        """Full-text search across model_id, display_name, and family."""
        if not self.db_path.exists():
            return []
        try:
            with self._conn() as conn:
                like = f"%{query}%"
                rows = conn.execute("""
                    SELECT m.model_id, m.display_name, m.family, m.status,
                           m.context_window, p.name AS provider,
                           ps.input_price_per_1m, ps.output_price_per_1m
                    FROM models m
                    JOIN providers p ON m.provider_id = p.id
                    LEFT JOIN pricing_snapshots ps
                        ON m.id = ps.model_id AND ps.effective_until IS NULL
                    WHERE m.model_id LIKE ? OR m.display_name LIKE ? OR m.family LIKE ?
                    ORDER BY p.name, m.model_id
                """, (like, like, like)).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_catalog: Optional[ModelCatalog] = None


def get_catalog(db_path: Optional[Path] = None) -> ModelCatalog:
    """Return the shared ModelCatalog instance (lazy-initialized)."""
    global _catalog
    resolved = db_path or bob_home_path("llm_database.db")
    if _catalog is None or _catalog.db_path != resolved:
        _catalog = ModelCatalog(resolved)
    return _catalog
