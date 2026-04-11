from __future__ import annotations

from bob.core.context_errors import classify_context_error


def test_classify_context_window_exceeded() -> None:
    c = classify_context_error("This model's maximum context window is exceeded.")
    assert c.kind == "context_window_exceeded"


def test_classify_max_output_exceeded() -> None:
    c = classify_context_error("finish_reason:length due to maximum output tokens")
    assert c.kind == "max_output_exceeded"


def test_classify_other() -> None:
    c = classify_context_error("network timeout")
    assert c.kind == "other"

