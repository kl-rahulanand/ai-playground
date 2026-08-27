"""Token accounting and cost estimation.

Prices are USD per 1,000,000 tokens, from the models overview (cached 2026-06).
Cache reads are ~0.1x the input rate; cache writes ~1.25x. These are estimates
for local reporting, not billing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# (input_per_mtok, output_per_mtok)
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
}

_CACHE_WRITE_MULT = 1.25   # writing to cache costs ~1.25x input
_CACHE_READ_MULT = 0.10    # reading from cache costs ~0.1x input


@dataclass(frozen=True)
class CostBreakdown:
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    input_cost: float
    output_cost: float
    cache_write_cost: float
    cache_read_cost: float

    @property
    def total(self) -> float:
        return self.input_cost + self.output_cost + self.cache_write_cost + self.cache_read_cost


def estimate_cost(model: str, usage) -> CostBreakdown:
    """Compute a cost breakdown from an SDK usage object.

    usage.input_tokens counts ONLY uncached input. Cache creation/read tokens are
    billed separately, which is why we break them out here.
    """
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cread = getattr(usage, "cache_read_input_tokens", 0) or 0

    return CostBreakdown(
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_write_tokens=cwrite,
        cache_read_tokens=cread,
        input_cost=inp / 1_000_000 * in_rate,
        output_cost=out / 1_000_000 * out_rate,
        cache_write_cost=cwrite / 1_000_000 * in_rate * _CACHE_WRITE_MULT,
        cache_read_cost=cread / 1_000_000 * in_rate * _CACHE_READ_MULT,
    )


class Timer:
    """Measure wall-clock latency:  with Timer() as t: ...   then t.seconds."""

    def __enter__(self):
        self._start = time.perf_counter()
        self.seconds = 0.0
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self._start
        return False
