"""Estimated model prices, used only to put a dollar figure on evaluation runs.

These are Anthropic's list prices per million tokens as of ``PRICES_AS_OF``, copied by hand.
They are estimates for comparing configurations: raw token counts are the authoritative record,
so any cost can be recomputed when prices change. Product behavior never depends on a price.
"""

from datetime import date
from typing import NamedTuple

from app.application.ai_planner import AttemptUsage

PRICES_AS_OF = date(2026, 10, 6)


class ModelPrice(NamedTuple):
    """US dollars per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


# (provider, model) -> price. Cache writes are taken as 1.25x input (five-minute cache), and
# Haiku's cache reads as 0.1x input; the planner does not request caching, so both are 0 today.
# Haiku 5.5's price applies to prompts up to 100K tokens; each planning call is far below that.
PRICES = {
    ("anthropic", "claude-haiku-5-5"): ModelPrice(0.10, 0.50, 0.01, 0.125),
    ("anthropic", "claude-sonnet-5-5"): ModelPrice(2.00, 10.00, 0.20, 2.50),
    ("anthropic", "claude-opus-5-5"): ModelPrice(4.00, 20.00, 0.20, 5.00),
}


def estimate_cost(usage: AttemptUsage) -> float | None:
    """Estimate an attempt's cost in US dollars from its raw token counts.

    Args:
        usage: The attempt's usage.

    Returns:
        The estimated cost, or None when the model has no listed price.
    """
    price = PRICES.get((usage.provider, usage.model))
    if price is None:
        return None
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.cache_read
        + usage.cache_creation_input_tokens * price.cache_write
    ) / 1_000_000
