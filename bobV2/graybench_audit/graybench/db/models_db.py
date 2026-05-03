"""CRUD operations for the models registry."""

import logging
from typing import Optional

from .engine import get_connection

log = logging.getLogger(__name__)


def list_models(provider: Optional[str] = None, active_only: bool = True) -> list[dict]:
    """List all models, optionally filtered by provider."""
    conn = get_connection()
    try:
        sql = "SELECT * FROM models WHERE provider != '_system'"
        params = []
        if provider:
            sql += " AND provider=?"
            params.append(provider)
        if active_only:
            sql += " AND status='active'"
        sql += " ORDER BY provider, model_id"
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_model(provider: str, model_id: str) -> Optional[dict]:
    """Get a specific model by provider and model_id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM models WHERE provider=? AND model_id=?",
            (provider, model_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_model(model_string: str) -> Optional[dict]:
    """Find a model by 'provider/model_id' string.

    Examples: 'google/gemini-3-flash-preview', 'openai/gpt-4o'
    """
    if "/" not in model_string:
        # Try matching model_id alone
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM models WHERE model_id=? AND status='active'",
                (model_string,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    provider, model_id = model_string.split("/", 1)
    return get_model(provider, model_id)


def add_model(provider: str, model_id: str, display_name: str,
              input_price_per_m: float = None, cached_price_per_m: float = None,
              output_price_per_m: float = None, openrouter_id: str = None,
              **kwargs) -> int:
    """Add a new model to the registry. Returns the row ID."""
    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO models (provider, model_id, display_name,
                               input_price_per_m, cached_price_per_m,
                               output_price_per_m, openrouter_id,
                               supports_json_mode, supports_reasoning,
                               supports_tools, long_context_note, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (provider, model_id, display_name,
              input_price_per_m, cached_price_per_m, output_price_per_m,
              openrouter_id,
              kwargs.get("supports_json_mode", 0),
              kwargs.get("supports_reasoning", 0),
              kwargs.get("supports_tools", 0),
              kwargs.get("long_context_note"),
              kwargs.get("notes")))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_model(provider: str, model_id: str, **kwargs) -> bool:
    """Update model fields. Returns True if found."""
    if not kwargs:
        return False
    allowed = {
        "display_name", "status", "input_price_per_m", "cached_price_per_m",
        "output_price_per_m", "context_window", "max_output_tokens",
        "supports_json_mode", "supports_reasoning", "supports_tools",
        "openrouter_id", "long_context_note", "batch_discount_pct", "notes",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [provider, model_id]

    conn = get_connection()
    try:
        cur = conn.execute(
            f"UPDATE models SET {set_clause}, updated_at=datetime('now') "
            f"WHERE provider=? AND model_id=?",
            values
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def remove_model(provider: str, model_id: str) -> bool:
    """Delete a model from the registry. Returns True if found."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM models WHERE provider=? AND model_id=?",
            (provider, model_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_pricing_notes() -> Optional[str]:
    """Get the stored pricing notes."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT notes FROM models WHERE provider='_system' AND model_id='_pricing_notes'"
        ).fetchone()
        return row["notes"] if row else None
    finally:
        conn.close()
