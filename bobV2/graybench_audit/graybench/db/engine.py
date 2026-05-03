"""SQLite database engine with migration support."""

import sqlite3
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "graybench.db"
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_db_path() -> Path:
    """Return the path to the SQLite database file."""
    return _DB_PATH


def get_connection(db_path: Path = None) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and foreign keys enabled."""
    path = db_path or _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(conn: sqlite3.Connection = None):
    """Run all pending SQL migration files in order."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        # Track which migrations have run
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        applied = {row[0] for row in conn.execute(
            "SELECT filename FROM _migrations"
        ).fetchall()}

        # Run pending migrations in sorted order
        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for mf in migration_files:
            if mf.name not in applied:
                log.info("Applying migration: %s", mf.name)
                sql = mf.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO _migrations (filename) VALUES (?)",
                    (mf.name,)
                )
                conn.commit()
                log.info("Migration applied: %s", mf.name)
    finally:
        if own_conn:
            conn.close()


def init_db():
    """Initialize the database and run all migrations."""
    conn = get_connection()
    try:
        run_migrations(conn)
    finally:
        conn.close()
    log.info("Database initialized at %s", _DB_PATH)
