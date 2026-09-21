"""Account for observed token usage using pinned configuration prices.

Owns: Per-request, per-buyer recorded cost and cache-token arithmetic.
Does not own: Provider billing reconciliation or speculative token estimates.
"""

from typing import Literal

from pydantic import BaseModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.errors import ConfigError, LLMInvalidOutput
from acquirer_engine.settings import ModelSpec

type ExecutionMode = Literal["live", "replay", "test"]


class CallRecord(BaseModel):
    """Usage received for one model request, including replay provenance."""

    acquirer: str
    stage: str = "analyst"
    model: str
    attempt: int
    mode: ExecutionMode
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: float


class CostLedger:
    """One run's append-only observed usage, shared across page tasks."""

    def __init__(self, model: ModelSpec) -> None:
        """Retain the pinned pricing snapshot.

        Args:
            model: Configured model identity and context-band prices.
        """
        self.model = model
        self.entries: list[CallRecord] = []

    @property
    def cost_usd(self) -> float:
        """Return new cost reported by requests in this invocation."""
        return sum(entry.cost_usd for entry in self.entries)

    def record(
        self,
        acquirer: str,
        attempt: int,
        usage: RequestUsage,
        latency_ms: float,
        *,
        mode: ExecutionMode,
        stage: str = "analyst",
    ) -> CallRecord:
        """Record actual normalized usage without double-counting cached input.

        Args:
            acquirer: Buyer owning this request.
            attempt: Model-request index within this buyer's conversation.
            usage: Provider response usage normalized by the framework.
            latency_ms: Measured request duration.
            mode: Replay and test calls incur no new provider cost.
        Returns:
            The recorded call, retaining original usage even during replay.
        Raises:
            LLMInvalidOutput: Live output has missing or inconsistent usage.
            ConfigError: Pricing does not cover this request.
        """
        uncached = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
        if uncached < 0 or (mode == "live" and usage.input_tokens + usage.output_tokens == 0):
            raise LLMInvalidOutput("Live response has zero tokens or inconsistent cached usage")
        cost = self._cost(usage, uncached)
        entry = CallRecord(
            acquirer=acquirer,
            model=self.model.model_id,
            stage=stage,
            attempt=attempt,
            mode=mode,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost if mode == "live" else 0,
            latency_ms=latency_ms,
        )
        self.entries.append(entry)
        return entry

    def _cost(self, usage: RequestUsage, uncached: int) -> float:
        price = next(
            (
                p
                for p in self.model.pricing
                if p.max_input_tokens is None or usage.input_tokens <= p.max_input_tokens
            ),
            None,
        )
        if price is None or price.cache_write_usd_per_million is None:
            raise ConfigError("No complete price band for request usage")
        return (
            uncached * price.input_usd_per_million
            + usage.output_tokens * price.output_usd_per_million
            + usage.cache_read_tokens * price.cache_read_usd_per_million
            + usage.cache_write_tokens * price.cache_write_usd_per_million
        ) / 1_000_000
