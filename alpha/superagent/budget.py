"""Budget tracking — per-call and session-cumulative cost and token accounting.

After every LLM call, prints one line to stdout:
  [llm] cost: $in/$out/$total  tokens: in/out/total  context: used/max (%)  session: $total Ntok
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Pricing per million tokens (input, output) — OpenRouter rates
# ---------------------------------------------------------------------------

# (input, output, cached_input) per million tokens
MODEL_PRICING: dict[str, tuple[float, float, float]] = {
    # Anthropic — cache read is 10% of input
    "anthropic/claude-opus-4.6": (15.0, 75.0, 1.50),
    "anthropic/claude-sonnet-4": (3.0, 15.0, 0.30),
    "anthropic/claude-haiku-3.5": (0.80, 4.0, 0.08),
    # OpenAI — cache read is 25% of input
    "openai/gpt-4.1-nano": (0.10, 0.40, 0.025),
    "openai/gpt-4.1-mini": (0.40, 1.60, 0.10),
    "openai/gpt-4.1": (2.0, 8.0, 0.50),
    "openai/o3": (2.0, 8.0, 0.50),
    "openai/o4-mini": (1.10, 4.40, 0.275),
    # Google — cache read is 25% of input
    "google/gemini-2.5-pro": (1.25, 10.0, 0.3125),
    "google/gemini-2.5-flash": (0.15, 0.60, 0.0375),
}

# Context window sizes (total tokens)
MODEL_CONTEXT: dict[str, int] = {
    "anthropic/claude-opus-4.6": 1_000_000,
    "anthropic/claude-sonnet-4": 200_000,
    "anthropic/claude-haiku-3.5": 200_000,
    "openai/gpt-4.1-nano": 1_048_576,
    "openai/gpt-4.1-mini": 1_048_576,
    "openai/gpt-4.1": 1_048_576,
    "openai/o3": 200_000,
    "openai/o4-mini": 200_000,
    "google/gemini-2.5-pro": 1_048_576,
    "google/gemini-2.5-flash": 1_048_576,
}

DEFAULT_CONTEXT = 128_000

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"


@dataclass
class CallStats:
    """Stats for a single LLM call."""

    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    input_cost: float
    output_cost: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT.get(self.model, DEFAULT_CONTEXT)


# ---------------------------------------------------------------------------
# Session-level budget accumulator (module-level singleton)
# ---------------------------------------------------------------------------


class _Budget:
    """Accumulates costs and tokens across a session."""

    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.total_cached_tokens: int = 0
        self.total_input_cost: float = 0.0
        self.total_output_cost: float = 0.0
        self.call_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost(self) -> float:
        return self.total_input_cost + self.total_output_cost

    def record(self, model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> CallStats:
        """Record one LLM call. Returns per-call stats.

        cached_tokens is a subset of input_tokens. Cost is calculated as:
          uncached * input_rate + cached * cached_rate + output * output_rate
        """
        pricing = MODEL_PRICING.get(model, (0.0, 0.0, 0.0))
        input_rate, output_rate, cached_rate = pricing[0], pricing[1], pricing[2]
        uncached = max(0, input_tokens - cached_tokens)
        input_cost = (uncached * input_rate + cached_tokens * cached_rate) / 1_000_000
        output_cost = output_tokens * output_rate / 1_000_000

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cached_tokens += cached_tokens
        self.total_input_cost += input_cost
        self.total_output_cost += output_cost
        self.call_count += 1

        return CallStats(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
        )

    def reset(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.total_input_cost = 0.0
        self.total_output_cost = 0.0
        self.call_count = 0


_budget = _Budget()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _fmt_cost(c: float) -> str:
    """Format a cost value with appropriate precision."""
    if c < 0.0001:
        return "$0"
    if c < 0.01:
        return f"${c:.4f}"
    return f"${c:.3f}"


def _fmt_tokens(n: int) -> str:
    """Format token count with K/M suffix for readability."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}K"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def record_and_print(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> None:
    """Record an LLM call and print a one-line summary."""
    stats = _budget.record(model, input_tokens, output_tokens, cached_tokens)
    ctx = stats.context_window
    used = stats.input_tokens + stats.output_tokens
    pct = used * 100 / ctx if ctx else 0

    # Short model name for display
    short_model = model.rsplit("/", 1)[-1] if "/" in model else model

    # Cached info
    cache_pct = stats.cached_tokens * 100 // stats.input_tokens if stats.input_tokens and stats.cached_tokens else 0

    print(
        f"{DIM}[llm]{RESET} "
        f"{short_model}  "
        f"cost: in{_fmt_cost(stats.input_cost)}/out{_fmt_cost(stats.output_cost)}/T{_fmt_cost(stats.total_cost)}  "
        f"tok: in{_fmt_tokens(stats.input_tokens)}/out{_fmt_tokens(stats.output_tokens)}/T{_fmt_tokens(stats.total_tokens)}  "
        f"cached: {_fmt_tokens(stats.cached_tokens)}({cache_pct}%)  "
        f"ctx: {_fmt_tokens(used)}/{_fmt_tokens(ctx)}({pct:.0f}%)  "
        f"{DIM}session: {_fmt_cost(_budget.total_cost)} {_fmt_tokens(_budget.total_tokens)}tok{RESET}",
        file=sys.stdout,
    )


def get_budget() -> _Budget:
    """Return the module-level budget instance."""
    return _budget


def reset_budget() -> None:
    """Reset the session budget (e.g. on /new)."""
    _budget.reset()


def budget_summary() -> str:
    """One-line budget summary for /status and system prompt."""
    return (
        f"calls={_budget.call_count}  "
        f"tokens={_fmt_tokens(_budget.total_input_tokens)}in/"
        f"{_fmt_tokens(_budget.total_output_tokens)}out/"
        f"{_fmt_tokens(_budget.total_tokens)}total  "
        f"cost={_fmt_cost(_budget.total_input_cost)}in/"
        f"{_fmt_cost(_budget.total_output_cost)}out/"
        f"{_fmt_cost(_budget.total_cost)}total"
    )
