from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

VIEW_IMAGE_DESCRIPTION = (
    "View a local image file and attach it to the conversation context."
)

VIEW_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the image file (relative to cwd or absolute).",
        },
    },
    "required": ["path"],
}

# MIME types bob recognises for inline attachment
_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}

_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB guard


async def view_image_handler(tool_input: dict, context: Any) -> str:
    """
    Load a local image and attach it as a base64 data-URL to the conversation.

    *context* must expose:
      - ``context.cwd``             – :class:`pathlib.Path`
      - ``context.attach_image``    – async callable ``(path, mime, b64) -> None``
                                      or ``None`` (metadata-only mode).
    """
    path_str: str = tool_input.get("path", "")
    if not path_str:
        return "Error: path is required"

    path = Path(path_str)
    if not path.is_absolute():
        path = context.cwd / path

    path = path.resolve()

    if not path.exists():
        return f"Error: image not found: {path}"
    if not path.is_file():
        return f"Error: not a file: {path}"

    ext = path.suffix.lower()
    mime = _MIME_MAP.get(ext)
    if mime is None:
        return (
            f"Error: unsupported image format '{ext}'. "
            f"Supported: {', '.join(_MIME_MAP)}"
        )

    size = path.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        return (
            f"Error: image too large ({size / 1024 / 1024:.1f} MB). "
            f"Maximum allowed size is {_MAX_IMAGE_BYTES // 1024 // 1024} MB."
        )

    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")

    # If the session has an attach_image callback, forward the image data
    # so it can be included in the next model request.
    attach = getattr(context, "attach_image", None)
    if attach is not None:
        await attach(str(path), mime, b64)
        return f"Image attached: {path.name} ({size:,} bytes, {mime})"

    # Fallback: return metadata only (the TUI/CLI layer may not support images)
    return f"Image loaded: {path.name} ({size:,} bytes, {mime}) [attachment not supported in this mode]"
