"""CRUD operations for API keys (Fernet-encrypted)."""

import os
import logging
from typing import Optional

from .engine import get_connection
from ..util.crypto import encrypt_key, decrypt_key

log = logging.getLogger(__name__)

# Environment variable names per provider
_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ibm_quantum": "QISKIT_IBM_TOKEN",
}


def set_key(provider: str, key: str, key_name: str = "default") -> None:
    """Store or update an encrypted API key."""
    encrypted = encrypt_key(key)
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO api_keys (provider, key_name, encrypted_key, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(provider, key_name)
            DO UPDATE SET encrypted_key=excluded.encrypted_key,
                         updated_at=datetime('now'),
                         is_active=1
        """, (provider, key_name, encrypted))
        conn.commit()
    finally:
        conn.close()


def get_key(provider: str, key_name: str = "default") -> Optional[str]:
    """Resolve an API key: env var first, then DB.

    Returns None if no key found.
    """
    # Check environment variable first
    env_var = _ENV_VARS.get(provider)
    if env_var:
        env_val = os.environ.get(env_var)
        if env_val:
            return env_val

    # Check database
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT encrypted_key FROM api_keys
            WHERE provider=? AND key_name=? AND is_active=1
        """, (provider, key_name)).fetchone()
        if row:
            return decrypt_key(row[0])
    finally:
        conn.close()
    return None


def list_keys() -> list[dict]:
    """List all configured providers (no key values shown)."""
    result = []
    # Show env var keys
    for provider, env_var in _ENV_VARS.items():
        if os.environ.get(env_var):
            result.append({
                "provider": provider,
                "key_name": "env",
                "source": f"${env_var}",
                "is_active": True,
            })

    # Show DB keys
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT provider, key_name, is_active, created_at, updated_at
            FROM api_keys ORDER BY provider, key_name
        """).fetchall()
        for row in rows:
            result.append({
                "provider": row["provider"],
                "key_name": row["key_name"],
                "source": "database",
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
    finally:
        conn.close()
    return result


def remove_key(provider: str, key_name: str = "default") -> bool:
    """Deactivate an API key. Returns True if found."""
    conn = get_connection()
    try:
        cur = conn.execute("""
            UPDATE api_keys SET is_active=0, updated_at=datetime('now')
            WHERE provider=? AND key_name=?
        """, (provider, key_name))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_key(provider: str, key_name: str = "default") -> bool:
    """Permanently delete an API key. Returns True if found."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM api_keys WHERE provider=? AND key_name=?",
            (provider, key_name)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
