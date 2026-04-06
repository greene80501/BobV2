from __future__ import annotations

import asyncio
import shutil
from typing import Any

JS_REPL_DESCRIPTION = (
    "Execute JavaScript code using Node.js and return stdout/stderr. "
    "Requires Node.js in PATH. Execution is capped at the timeout value."
)

JS_REPL_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "JavaScript code to execute.",
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in milliseconds (default: 10000, max: 30000).",
        },
    },
    "required": ["code"],
}

MAX_TIMEOUT_MS = 30_000
DEFAULT_TIMEOUT_MS = 10_000


async def js_repl_handler(tool_input: dict, context: Any) -> str:
    code: str = tool_input.get("code", "")
    if not code:
        return "Error: code is required"

    timeout_ms: int = min(tool_input.get("timeout", DEFAULT_TIMEOUT_MS), MAX_TIMEOUT_MS)
    timeout_s = timeout_ms / 1000

    node = shutil.which("node")
    if not node:
        return "Error: Node.js not found in PATH. Install Node.js to use js_repl."

    cancel_event = getattr(context, "cancel_event", None)

    try:
        proc = await asyncio.create_subprocess_exec(
            node, "--input-type=module",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return f"Error starting Node.js: {exc}"

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=code.encode()),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"[Timed out after {timeout_ms}ms]"
    except asyncio.CancelledError:
        try:
            proc.kill()
        except Exception:
            pass
        raise

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    parts: list[str] = []
    if stdout:
        parts.append(stdout.rstrip())
    if stderr:
        parts.append(f"[stderr]\n{stderr.rstrip()}")

    return "\n".join(parts) if parts else "(no output)"
