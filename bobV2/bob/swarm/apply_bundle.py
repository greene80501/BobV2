from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_current(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    return True, path.read_bytes().decode("utf-8", errors="replace")


def apply_swarm_bundle(payload_text: str, cwd: Path) -> dict[str, Any]:
    """Apply a bob_swarm_bundle_v1 payload with conflict checks."""
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        return {"applied": 0, "skipped": 0, "errors": [f"Invalid swarm bundle JSON: {exc}"]}

    if payload.get("format") != "bob_swarm_bundle_v1":
        return {"applied": 0, "skipped": 0, "errors": ["Unsupported swarm patch format"]}

    applied = 0
    skipped = 0
    errors: list[str] = []
    seen_paths: set[str] = set()

    for bundle in payload.get("bundles", []):
        for item in bundle.get("files", []):
            rel = str(item.get("path") or "").strip()
            if not rel:
                skipped += 1
                errors.append("Skipped change with empty path")
                continue
            if rel in seen_paths:
                skipped += 1
                errors.append(f"Skipped duplicate change for {rel}")
                continue
            seen_paths.add(rel)

            operation = item.get("operation")
            if operation == "unsupported_binary":
                skipped += 1
                errors.append(f"Skipped unsupported binary file: {rel}")
                continue
            if operation not in {"write", "delete"}:
                skipped += 1
                errors.append(f"Skipped unsupported operation for {rel}: {operation}")
                continue

            target = (cwd / rel).resolve()
            try:
                target.relative_to(cwd.resolve())
            except ValueError:
                skipped += 1
                errors.append(f"Skipped path outside workspace: {rel}")
                continue

            old_hash = item.get("old_sha256")
            exists, current_text = _read_current(target)
            current_hash = _sha256_text(current_text) if current_text is not None else None
            if current_hash != old_hash:
                skipped += 1
                errors.append(f"Skipped conflicted file: {rel}")
                continue

            try:
                if operation == "delete":
                    if exists:
                        target.unlink()
                    applied += 1
                else:
                    content = item.get("content")
                    if not isinstance(content, str):
                        skipped += 1
                        errors.append(f"Skipped write without text content: {rel}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content.encode("utf-8"))
                    applied += 1
            except OSError as exc:
                skipped += 1
                errors.append(f"Error applying {rel}: {exc}")

    return {"applied": applied, "skipped": skipped, "errors": errors}
