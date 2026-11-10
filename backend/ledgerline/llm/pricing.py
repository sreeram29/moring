"""Token pricing for the cost dashboard and the llm_calls table."""
from __future__ import annotations

import os

# USD per ONE MILLION tokens: (input, output).
# Until Nov 2026 these were off by 1000x (they were per-1K figures labelled per-million), which is why
# the dashboard said Rs 15 for a month the provider billed ~$165 (Rs 14,500). Check against the
# provider's pricing page before relying on them, or override with the environment variables below.
USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "anthropic/claude-haiku-4.5": (1.0, 5.0),   # OpenRouter name; check openrouter.ai/anthropic/claude-haiku-4.5
    "google/gemma-4-31b-it:free": (0.0, 0.0),   # OpenRouter free tier
    "gpt-4o-mini": (0.15, 0.60),
    "fake": (0.0, 0.0),
}


class UnknownModelPrice(ValueError):
    pass


def price_for(model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens. Raises for an unpriced model instead of costing it at zero."""
    override_in, override_out = os.getenv("LLM_PRICE_IN_USD_PER_MTOK"), os.getenv("LLM_PRICE_OUT_USD_PER_MTOK")
    if override_in is not None and override_out is not None:
        return float(override_in), float(override_out)
    if model not in USD_PER_MTOK:
        raise UnknownModelPrice(
            f"No price for model {model!r}. Add it to llm/pricing.py, or set LLM_PRICE_IN_USD_PER_MTOK and "
            "LLM_PRICE_OUT_USD_PER_MTOK (use 0 for a local model)."
        )
    return USD_PER_MTOK[model]


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = price_for(model)
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000