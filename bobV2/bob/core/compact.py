from __future__ import annotations

from dataclasses import dataclass
import json
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


@dataclass(frozen=True)
class CompactionResult:
    summary_text: str
    old_history: list[dict]
    new_history: list[dict]
    reason: str
    token_before: int
    token_after: int


def approx_token_count(text: str) -> int:
    return len(text) // 4


def is_summary_message(text: str) -> bool:
    return text.startswith(SUMMARY_PREFIX)


def collect_user_messages(history: list[dict]) -> list[str]:
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


def build_compacted_history(user_messages: list[str], summary_text: str) -> list[dict]:
    selected: list[str] = []
    remaining = COMPACT_USER_MESSAGE_MAX_TOKENS
    for msg in reversed(user_messages):
        tokens = approx_token_count(msg)
        if tokens <= remaining:
            selected.insert(0, msg)
            remaining -= tokens
        else:
            break

    history: list[dict] = [
        {"role": "user", "content": [{"type": "input_text", "text": msg}]}
        for msg in selected
    ]
    history.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": summary_text}],
        }
    )
    return history


def _is_prompt_too_long(message: str) -> bool:
    m = (message or "").lower()
    return any(
        key in m
        for key in (
            "prompt too long",
            "maximum context",
            "context window",
            "too many tokens",
            "context_length_exceeded",
            "input is too long",
        )
    )


async def run_compact(
    session: "BobSession",
    *,
    reason: str = "manual",
    hint: Optional[str] = None,
    max_retries: Optional[int] = None,
) -> Optional[CompactionResult]:
    from bob.llm.client import TextDeltaEvent, StreamErrorEvent  # type: ignore
    from bob.protocol.config_types import HookEventName

    # Fire pre-compact hooks (blocking hooks can veto compaction)
    _hook_runner = getattr(session, "hook_runner", None)
    if _hook_runner is not None:
        hook_ctx = {"reason": reason, "hint": hint or ""}
        pre_results = await _hook_runner.run_hooks(HookEventName.PRE_COMPACT, hook_ctx)
        if any(r.blocked for r in pre_results):
            return None

    old_history = session.context_manager.raw_items()
    token_before = session.context_manager.approx_token_count()
    retries = max_retries
    if retries is None:
        retries = int(getattr(session.config, "compact_max_retries", 3) or 3)
    retries = max(0, retries)

    prompt = SUMMARIZATION_PROMPT
    if hint:
        prompt += f"\n\nAdditional preservation hint:\n{hint}"

    compact_input: list[dict] = list(old_history) + [
        {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
    ]

    for _attempt in range(retries + 1):
        summary_parts: list[str] = []
        stream_error: str | None = None
        try:
            async for event in session.client.stream_turn(
                input=compact_input,
                instructions="Produce a concise handoff summary.",
                tools=[],
            ):
                if isinstance(event, TextDeltaEvent):
                    summary_parts.append(event.delta)
                elif isinstance(event, StreamErrorEvent):
                    stream_error = event.message
        except Exception as exc:
            stream_error = str(exc)

        summary = "".join(summary_parts).strip()
        if summary:
            summary_text = f"{SUMMARY_PREFIX}\n{summary}"
            user_messages = collect_user_messages(old_history)
            new_history = build_compacted_history(user_messages, summary_text)
            token_after = len(json.dumps(new_history)) // 4
            result = CompactionResult(
                summary_text=summary_text,
                old_history=old_history,
                new_history=new_history,
                reason=reason,
                token_before=token_before,
                token_after=token_after,
            )
            # Fire post-compact hooks asynchronously — no return value used
            if _hook_runner is not None:
                await _hook_runner.run_hooks(HookEventName.POST_COMPACT, {
                    "reason": reason,
                    "token_before": token_before,
                    "token_after": token_after,
                    "tokens_saved": token_before - token_after,
                })
            return result

        if not _is_prompt_too_long(stream_error or ""):
            return None
        if len(compact_input) <= 3:
            return None
        compact_input = compact_input[1:]

    return None
