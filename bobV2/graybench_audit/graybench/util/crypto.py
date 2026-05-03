"""Fernet encryption for API key storage."""

import os
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet


_SALT = b"graybench-api-key-store-v1"


def _get_keyring_path() -> Path:
    """Return path to the machine-local keyring file."""
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / ".keyring"


def _get_or_create_key() -> bytes:
    """Get or create the Fernet encryption key."""
    keyring = _get_keyring_path()
    if keyring.exists():
        return keyring.read_bytes()

    # Generate a passphrase and derive a Fernet key
    passphrase = os.urandom(32)
    dk = hashlib.pbkdf2_hmac("sha256", passphrase, _SALT, 100_000, dklen=32)
    fernet_key = base64.urlsafe_b64encode(dk)

    keyring.write_bytes(fernet_key)
    try:
        keyring.chmod(0o600)
    except OSError:
        pass  # Windows may not support chmod
    return fernet_key


def _get_fernet() -> Fernet:
    return Fernet(_get_or_create_key())


def encrypt_key(plaintext: str) -> bytes:
    """Encrypt an API key string, returning Fernet token bytes."""
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_key(token: bytes) -> str:
    """Decrypt Fernet token bytes back to the API key string."""
    return _get_fernet().decrypt(token).decode("utf-8")
