"""Build the LLM model catalog database into ~/.bob/llm_database.db.

Run this once (and again when providers release new models or change pricing):

    python scripts/build_model_catalog.py

Requires the llm-database package to be installed:
    pip install -e C:\\Users\\green\\hevay_llm\\LLM-database

API keys (set whichever providers you want to update):
    $env:OPENAI_API_KEY     = "sk-..."
    $env:ANTHROPIC_API_KEY  = "sk-ant-..."
    $env:GEMINI_API_KEY     = "..."
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

BOB_HOME   = Path(os.environ.get("BOB_HOME", Path.home() / ".bob"))
TARGET     = BOB_HOME / "llm_database.db"
LLM_DB_DIR = Path(r"C:\Users\green\hevay_llm\LLM-database")


def main() -> None:
    BOB_HOME.mkdir(parents=True, exist_ok=True)

    # ── Ensure llm-database is importable ─────────────────────────────
    try:
        import llm_database  # noqa: F401
    except ImportError:
        print("Installing llm-database from local source…")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-e", str(LLM_DB_DIR), "-q"
        ])

    # ── Run the updater — it writes llm_database.db in CWD by default ─
    import tempfile, os as _os
    with tempfile.TemporaryDirectory() as tmp:
        print(f"Fetching model data from provider APIs…  (this may take ~30s)")
        env = {**_os.environ}  # inherit all API keys
        result = subprocess.run(
            [sys.executable, "-m", "llm_database.update"],
            cwd=tmp,
            env=env,
            capture_output=False,
        )
        built = Path(tmp) / "llm_database.db"
        if result.returncode != 0 or not built.exists():
            print("ERROR: llm_database.update failed — check your API keys.")
            sys.exit(1)

        shutil.copy2(built, TARGET)

    print(f"\n✓ Model catalog written to {TARGET}")

    # ── Quick summary ──────────────────────────────────────────────────
    import sqlite3
    conn = sqlite3.connect(TARGET)
    row = conn.execute("SELECT COUNT(*) FROM models").fetchone()
    prow = conn.execute("SELECT COUNT(*) FROM providers").fetchone()
    conn.close()
    print(f"  {prow[0]} providers  ·  {row[0]} models")
    print("\nBob will use this catalog automatically for cost tracking.")


if __name__ == "__main__":
    main()
