from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextErrorClassification:
    kind: str
    message: str


def classify_context_error(message: str) -> ContextErrorClassification:
    msg = (message or "").lower()
    if not msg:
        return ContextErrorClassification(kind="other", message=message or "")

    context_tokens = (
        "maximum context",
        "context window",
        "prompt is too long",
        "input is too long",
        "too many tokens",
        "prompt too long",
        "context_length_exceeded",
        "token limit",
    )
    max_output_tokens = (
        "max_output_tokens",
        "maximum output tokens",
        "output token limit",
        "finish_reason:length",
        "finish_reason: length",
        "length limit",
    )

    if any(s in msg for s in context_tokens):
        return ContextErrorClassification(kind="context_window_exceeded", message=message)
    if any(s in msg for s in max_output_tokens):
        return ContextErrorClassification(kind="max_output_exceeded", message=message)
    return ContextErrorClassification(kind="other", message=message)

