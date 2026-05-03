"""Token counting and cost calculation."""

import logging
from typing import Optional

from ..db import models_db
from .base import LLMResponse

log = logging.getLogger(__name__)


def calculate_cost(response: LLMResponse) -> float:
    """Calculate the USD cost of an LLM response based on model pricing.

    Uses the models DB for pricing data. Returns 0.0 if pricing unknown.
    """
    model_info = models_db.get_model(response.provider, response.model)
    if not model_info:
        # Try finding by model_id alone
        model_info = models_db.find_model(response.model)
    if not model_info:
        return 0.0

    input_price = model_info.get("input_price_per_m") or 0.0
    cached_price = model_info.get("cached_price_per_m")
    output_price = model_info.get("output_price_per_m") or 0.0

    # Calculate input cost (separate cached and non-cached tokens)
    non_cached_input = response.input_tokens - response.cached_tokens
    if cached_price is not None and response.cached_tokens > 0:
        input_cost = (non_cached_input * input_price + response.cached_tokens * cached_price) / 1_000_000
    else:
        input_cost = response.input_tokens * input_price / 1_000_000

    # Calculate output cost
    output_cost = response.output_tokens * output_price / 1_000_000

    total = input_cost + output_cost
    return round(total, 6)


def format_cost(cost_usd: float) -> str:
    """Format a cost value for display."""
    if cost_usd < 0.001:
        return f"${cost_usd:.6f}"
    elif cost_usd < 1.0:
        return f"${cost_usd:.4f}"
    else:
        return f"${cost_usd:.2f}"


def format_tokens(count: int) -> str:
    """Format a token count for display."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
