"""Per-turn analytics tracker.

Ties together:
  - ModelCatalog  → looks up per-token pricing
  - AnalyticsDB   → persists each turn record
  - In-memory     → accumulates session totals for fast display

Usage (from turn.py):
    tracker = session.analytics
    tracker.start_turn(session.session_id, turn_id, session.config.model)
    # … run model call …
    await tracker.finish_turn(input_tokens, output_tokens)

    # TUI reads:
    tracker.last_turn_cost_usd   → float or None
    tracker.session_cost_usd     → float
    tracker.session_tokens       → int
"""

from __future__ import annotations

import time
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bob.analytics.db import AnalyticsDB
    from bob.llm.catalog import ModelCatalog

logger = logging.getLogger(__name__)


class AnalyticsTracker:
    """Tracks tokens, cost, and latency per turn for a Bob session."""

    def __init__(self, db: "AnalyticsDB", catalog: "ModelCatalog") -> None:
        self._db = db
        self._catalog = catalog

        # Current turn state
        self._session_id: str = ""
        self._turn_id: Optional[str] = None
        self._model: str = ""
        self._start_time: float = 0.0

        # Session accumulators
        self._session_input_tokens: int = 0
        self._session_output_tokens: int = 0
        self._session_cost_usd: float = 0.0
        self._session_turns: int = 0

        # Last turn (for display after each response)
        self.last_turn_input_tokens: int = 0
        self.last_turn_output_tokens: int = 0
        self.last_turn_cost_usd: Optional[float] = None
        self.last_turn_latency_ms: Optional[int] = None

    # ------------------------------------------------------------------
    # Turn lifecycle
    # ------------------------------------------------------------------

    def start_turn(self, session_id: str, turn_id: str, model: str) -> None:
        """Call at the start of each turn to begin timing."""
        self._session_id = session_id
        self._turn_id = turn_id
        self._model = model
        self._start_time = time.monotonic()

    async def finish_turn(self, input_tokens: int, output_tokens: int) -> None:
        """Call after the model stream ends with the token counts.

        Computes cost via the model catalog, updates session accumulators,
        and persists the record to the analytics DB.
        """
        latency_ms = int((time.monotonic() - self._start_time) * 1000) if self._start_time else None

        # Cost calculation from catalog pricing
        pricing = self._catalog.get_pricing(self._model)
        if pricing and (input_tokens or output_tokens):
            input_cost  = (input_tokens  / 1_000_000) * pricing["input_per_1m"]
            output_cost = (output_tokens / 1_000_000) * pricing["output_per_1m"]
            total_cost  = input_cost + output_cost
        else:
            input_cost  = None
            output_cost = None
            total_cost  = None

        total_tokens = input_tokens + output_tokens

        # Update last-turn display values
        self.last_turn_input_tokens  = input_tokens
        self.last_turn_output_tokens = output_tokens
        self.last_turn_cost_usd      = total_cost
        self.last_turn_latency_ms    = latency_ms

        # Update session accumulators
        self._session_input_tokens  += input_tokens
        self._session_output_tokens += output_tokens
        self._session_cost_usd      += total_cost or 0.0
        self._session_turns         += 1

        # Derive provider from model name prefix
        provider = _infer_provider(self._model)

        # Persist
        await self._db.record_turn(
            session_id   = self._session_id,
            turn_id      = self._turn_id,
            model        = self._model,
            provider     = provider,
            input_tokens = input_tokens,
            output_tokens= output_tokens,
            total_tokens = total_tokens,
            input_cost_usd  = input_cost,
            output_cost_usd = output_cost,
            total_cost_usd  = total_cost,
            latency_ms   = latency_ms,
        )

    # ------------------------------------------------------------------
    # Session-level aggregates (read by TUI for /cost, /usage commands)
    # ------------------------------------------------------------------

    @property
    def session_input_tokens(self) -> int:
        return self._session_input_tokens

    @property
    def session_output_tokens(self) -> int:
        return self._session_output_tokens

    @property
    def session_tokens(self) -> int:
        return self._session_input_tokens + self._session_output_tokens

    @property
    def session_cost_usd(self) -> float:
        return self._session_cost_usd

    @property
    def session_turns(self) -> int:
        return self._session_turns

    # ------------------------------------------------------------------
    # Formatted helpers for TUI display
    # ------------------------------------------------------------------

    def format_last_turn_status(self, model: str = "", context_window: Optional[int] = None) -> str:
        """Return a dim one-liner suitable for display after each model response.

        Example:
            claude-3-5-sonnet  ·  1,234 in  456 out  ·  $0.018  ·  12% ctx
        """
        parts: list[str] = []
        if model:
            parts.append(model)
        parts.append(
            f"{self.last_turn_input_tokens:,} in  "
            f"{self.last_turn_output_tokens:,} out"
        )
        if self.last_turn_cost_usd is not None:
            parts.append(f"${self.last_turn_cost_usd:.4f}")
        if context_window and self.session_tokens:
            pct = min(100, int(self.session_tokens / context_window * 100))
            parts.append(f"{pct}% ctx")
        if self.last_turn_latency_ms is not None:
            parts.append(f"{self.last_turn_latency_ms:,}ms")
        return "  ·  ".join(parts)

    def format_session_cost(self) -> str:
        """Return a summary string for the /cost slash command."""
        lines = [
            f"Session cost:   ${self._session_cost_usd:.4f}",
            f"Total tokens:   {self.session_tokens:,}  "
            f"({self._session_input_tokens:,} in + {self._session_output_tokens:,} out)",
            f"Turns:          {self._session_turns}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_provider(model: str) -> Optional[str]:
    m = model.lower()
    if "/" in m:
        return m.split("/")[0]
    if m.startswith(("gpt-", "o1", "o3", "o4", "text-")):
        return "openai"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-"):
        return "google"
    if m.startswith(("kimi-", "moonshot-")):
        return "moonshot"
    if m.startswith("glm-"):
        return "glm"
    return None
