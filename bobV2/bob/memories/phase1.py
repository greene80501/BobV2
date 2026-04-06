from __future__ import annotations
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.client.openai_client import BobClient
    from bob.memories.storage import MemoryStorage

# Maximum number of conversation messages to include in the extraction prompt
_MAX_MESSAGES = 60
# Approximate character limit for the session text fed to the model
_MAX_CHARS = 12_000


async def extract_memories_from_rollout(
    rollout_path: Path,
    client: "BobClient",
    session_id: str,
    storage: "MemoryStorage",
) -> Optional[str]:
    """Phase 1 memory extraction: scan a rollout file and extract memorable facts.

    The resulting summary is written to *storage* and returned as a string.
    Returns ``None`` if nothing noteworthy was found or extraction failed.
    """
    from bob.rollout.recorder import load_rollout
    from bob.client.openai_client import TextDeltaEvent

    items = await load_rollout(rollout_path)
    if not items:
        return None

    # Build a condensed conversation transcript from the rollout events
    messages: list[str] = []
    for item in items:
        item_type = item.get("type")

        if item_type == "user_message":
            for content_item in item.get("items", []):
                if isinstance(content_item, dict):
                    text = content_item.get("text", "")
                    if text.strip():
                        messages.append(f"User: {text[:400]}")

        elif item_type == "response_item":
            resp = item.get("item", {})
            if resp.get("role") == "assistant":
                for c in resp.get("content", []):
                    if isinstance(c, dict) and c.get("type") == "output_text":
                        text = c.get("text", "")
                        if text.strip():
                            messages.append(f"Bob: {text[:400]}")

    if not messages:
        return None

    # Limit to the last _MAX_MESSAGES exchanges
    messages = messages[-_MAX_MESSAGES:]
    session_text = "\n".join(messages)

    # Rough character cap to avoid huge prompts
    if len(session_text) > _MAX_CHARS:
        session_text = session_text[-_MAX_CHARS:]

    extraction_prompt = (
        "Review this conversation excerpt and extract any facts that would be useful "
        "to remember for future sessions.\n\n"
        "Focus on:\n"
        "- User preferences and working style\n"
        "- Project-specific facts, conventions, or constraints\n"
        "- Important decisions made\n"
        "- Technologies, libraries, or tools in use\n"
        "- Recurring patterns or things the user cares about\n\n"
        f"Conversation:\n{session_text}\n\n"
        "Respond with a concise bullet list of memorable facts. "
        "If nothing is worth remembering, respond exactly with: (nothing to remember)"
    )

    parts: list[str] = []
    try:
        async for ev in client.stream_turn(
            input=[{
                "role": "user",
                "content": [{"type": "input_text", "text": extraction_prompt}],
            }],
            instructions="Extract useful memories from the conversation excerpt.",
            tools=[],
        ):
            if isinstance(ev, TextDeltaEvent):
                parts.append(ev.delta)
    except Exception:
        return None

    summary = "".join(parts).strip()
    if not summary or "(nothing to remember)" in summary.lower():
        return None

    storage.write_summary(session_id, summary)
    return summary
