from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bob.llm.catalog import get_catalog


@dataclass(frozen=True)
class ContextBudget:
    model_context_window: int
    effective_context_window: int
    compact_trigger_tokens: int
    reserve_output_tokens: int
    trigger_buffer_tokens: int


def _resolve_model_context_window(session) -> Optional[int]:
    if getattr(session.config, "max_context_tokens", 0):
        return int(session.config.max_context_tokens)

    try:
        compatibility, _ = session.get_model_runtime(session.config.model)
        model_id = compatibility.canonical_model
    except Exception:
        model_id = session.config.model

    return get_catalog().get_context_window(model_id)


def compute_context_budget(session) -> ContextBudget:
    model_window = _resolve_model_context_window(session) or 200_000
    pct = float(getattr(session.config, "effective_context_window_percent", 0.85) or 0.85)
    pct = max(0.1, min(0.98, pct))
    reserve = max(0, int(getattr(session.config, "compact_reserve_output_tokens", 12_000) or 0))
    buffer_tokens = max(0, int(getattr(session.config, "compact_trigger_buffer_tokens", 8_000) or 0))

    effective = int(model_window * pct) - reserve
    effective = max(10_000, min(model_window, effective))
    trigger = max(5_000, effective - buffer_tokens)
    trigger = min(trigger, effective)

    return ContextBudget(
        model_context_window=model_window,
        effective_context_window=effective,
        compact_trigger_tokens=trigger,
        reserve_output_tokens=reserve,
        trigger_buffer_tokens=buffer_tokens,
    )


def should_compact(token_count: int, budget: ContextBudget, configured_threshold: int = 0) -> bool:
    if configured_threshold and configured_threshold > 0:
        return token_count >= configured_threshold
    return token_count >= budget.compact_trigger_tokens

