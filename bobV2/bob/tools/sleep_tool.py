from __future__ import annotations

import asyncio
from typing import Any

SLEEP_DESCRIPTION = (
    "Pause execution for a number of seconds. Maximum 300 seconds. "
    "Respects cancellation."
)

SLEEP_SCHEMA = {
    "type": "object",
    "properties": {
        "seconds": {
            "type": "number",
            "description": "Number of seconds to sleep (0–300).",
        },
    },
    "required": ["seconds"],
}

MAX_SLEEP_SECONDS = 300


async def sleep_handler(tool_input: dict, context: Any) -> str:
    seconds = float(tool_input.get("seconds", 0))
    if seconds < 0:
        return "Error: seconds must be >= 0"
    seconds = min(seconds, MAX_SLEEP_SECONDS)

    cancel_event = getattr(context, "cancel_event", None)

    # Sleep in small chunks so we can respect cancellation
    elapsed = 0.0
    chunk = 0.1
    while elapsed < seconds:
        if cancel_event is not None and cancel_event.is_set():
            return f"Sleep cancelled after {elapsed:.1f}s"
        remaining = seconds - elapsed
        await asyncio.sleep(min(chunk, remaining))
        elapsed += chunk

    return f"Slept for {seconds:.1f}s"
