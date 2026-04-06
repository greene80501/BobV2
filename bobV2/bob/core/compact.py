from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from bob.core.session import BobSession

SUMMARIZATION_PROMPT = (
    "You are performing a CONTEXT CHECKPOINT COMPACTION. "
    "Create a handoff summary for another LLM that will resume the task.\n\n"
    "Include:\n"
    "- Current progress and key decisions made\n"
    "- Important context, constraints, or user preferences\n"
    "- What remains to be done (clear next steps)\n"
    "- Any critical data, examples, or references needed to continue\n\n"
    "Be concise, structured, and focused on helping the next LLM seamlessly "
    "continue the work."
)

SUMMARY_PREFIX = "Context compaction summary:"
COMPACT_USER_MESSAGE_MAX_TOKENS = 20_000


def approx_token_count(text: str) -> int:
    """Rough token estimate: character count divided by 4."""
    return len(text) // 4


def is_summary_message(text: str) -> bool:
    """Return True if *text* is itself a prior compaction summary."""
    return text.startswith(SUMMARY_PREFIX)


def collect_user_messages(history: list[dict]) -> list[str]:
    """
    Extract all non-summary user-turn text messages from *history*.

    Tool results (items with "tool_call_id") are skipped.
    Items whose combined text is a prior summary are also skipped.
    """
    messages: list[str] = []
    for item in history:
        if item.get("role") != "user":
            continue
        if "tool_call_id" in item:
            continue
        content = item.get("content", [])
        texts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") in ("input_text", "text"):
                texts.append(c.get("text", ""))
            elif isinstance(c, str):
                texts.append(c)
        combined = " ".join(t for t in texts if t)
        if combined and not is_summary_message(combined):
            messages.append(combined)
    return messages


def build_compacted_history(
    user_messages: list[str],
    summary_text: str,
) -> list[dict]:
    """
    Build a minimal history consisting of:
      1. The most-recent user messages that fit within the token budget.
      2. The compaction summary as the final user message.

    The token budget prevents the compacted history from itself being too large.
    """
    selected: list[str] = []
    remaining = COMPACT_USER_MESSAGE_MAX_TOKENS

    # Walk messages from newest to oldest; keep as many as the budget allows.
    for msg in reversed(user_messages):
        tokens = approx_token_count(msg)
        if tokens <= remaining:
            selected.insert(0, msg)
            remaining -= tokens
        else:
            # Stop as soon as the next message would overflow the budget.
            break

    history: list[dict] = []
    for msg in selected:
        history.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": msg}],
            }
        )

    # Always append the summary as the final context anchor.
    history.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": summary_text}],
        }
    )
    return history


async def run_compact(session: "BobSession") -> Optional[str]:
    """
    Run context compaction against the current session history.

    Sends the full history to the model with a summarization instruction,
    replaces session history with the compacted version, and returns the
    summary text.  Returns None on failure (history is left unchanged).
    """
    # Import here to avoid circular deps at module level.
    from bob.client.openai_client import TextDeltaEvent  # type: ignore

    history = session.context_manager.raw_items()

    # Build the compaction request: full history + compaction instruction
    compact_input: list[dict] = list(history) + [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": SUMMARIZATION_PROMPT}],
        }
    ]

    summary_parts: list[str] = []
    try:
        async for event in session.client.stream_turn(
            input=compact_input,
            instructions="Produce a concise handoff summary.",
            tools=[],
        ):
            if isinstance(event, TextDeltaEvent):
                summary_parts.append(event.delta)
    except Exception:
        return None

    summary = "".join(summary_parts).strip()
    if not summary:
        return None

    summary_text = f"{SUMMARY_PREFIX}\n{summary}"
    user_messages = collect_user_messages(history)
    new_history = build_compacted_history(user_messages, summary_text)

    session.context_manager.replace(new_history)
    return summary_text
