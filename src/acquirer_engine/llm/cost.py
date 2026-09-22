"""Admit concurrent requests and account for their returned usage.

Owns: Cost ledger, token estimates, shared reservations, and uncertain charges.
Does not own: Provider billing reconciliation, generation, or validation.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, NonNegativeFloat, TypeAdapter
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from acquirer_engine.errors import BudgetExceeded, ConfigError, LLMInvalidOutput
from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.settings import ModelSpec

type ExecutionMode = Literal["live", "replay", "test"]


class RequestTiming(BaseModel):
    """Separate preflight and budget waits from the measured provider call."""

    token_count_ms: NonNegativeFloat
    admission_ms: NonNegativeFloat
    provider_ms: NonNegativeFloat


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
    timing: RequestTiming | None = None


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
        model: ModelSpec | None = None,
        timing: RequestTiming | None = None,
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
        spec = model or self.model
        cost = self._cost(usage, uncached, spec)
        entry = CallRecord(
            acquirer=acquirer,
            model=spec.model_id,
            stage=stage,
            attempt=attempt,
            mode=mode,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost if mode == "live" else 0,
            latency_ms=latency_ms,
            timing=timing,
        )
        self.entries.append(entry)
        return entry

    def _cost(self, usage: RequestUsage, uncached: int, spec: ModelSpec) -> float:
        price = next(
            (
                p
                for p in spec.pricing
                if p.max_input_tokens is None or usage.input_tokens <= p.max_input_tokens
            ),
            None,
        )
        if price is None or (
            usage.cache_write_tokens and price.cache_write_usd_per_million is None
        ):
            raise ConfigError("No complete price band for request usage")
        return (
            uncached * price.input_usd_per_million
            + usage.output_tokens * price.output_usd_per_million
            + usage.cache_read_tokens * price.cache_read_usd_per_million
            + usage.cache_write_tokens * (price.cache_write_usd_per_million or 0)
        ) / 1_000_000


@dataclass
class Charge:
    """Returned usage replaces a reservation; absent usage remains uncertain."""

    actual: float | None = None


class RunBudget:
    """One shared budget admits concurrent work without spending the same dollar twice."""

    def __init__(self, limit: float | None) -> None:
        self.limit = limit
        self.spent = 0.0
        self.reserved = 0.0
        self.uncertain = 0.0
        self.condition = asyncio.Condition()

    async def reserve(self, amount: float) -> None:
        """Wait for inflight usage, or reject requests that cannot fit the budget.

        Args:
            amount: Conservative maximum cost for this request.
        Raises:
            BudgetExceeded: The remaining run budget cannot admit this request.
        """
        async with self.condition:
            while self.limit is not None and self.spent + self.reserved + amount > self.limit:
                if self.spent + amount > self.limit or self.reserved <= 0:
                    raise BudgetExceeded("Run USD budget cannot admit another request")
                await self.condition.wait()
            self.reserved += amount

    async def settle(self, reservation: float, actual: float | None) -> None:
        """Replace reserved spend with returned usage, retaining uncertain failed charges.

        Args:
            reservation: Amount admitted before execution.
            actual: Observed USD, or None if the provider returned no usable usage.
        """
        async with self.condition:
            self.reserved = max(0, self.reserved - reservation)
            self.spent += reservation if actual is None else actual
            if actual is None:
                self.uncertain += reservation
            self.condition.notify_all()

    @asynccontextmanager
    async def claim(self, amount: float) -> AsyncIterator[Charge]:
        """Hold a reservation until execution succeeds, fails, or is cancelled."""
        await self.reserve(amount)
        charge = Charge()
        try:
            yield charge
        finally:
            await self.settle(amount, charge.actual)


def request_bound(spec: ModelSpec, input_tokens: int, output_tokens: int, retries: int) -> float:
    """Price a guarded input estimate and the full output cap at the highest price.

    Args:
        spec: Pinned pricing, including cache write prices.
        input_tokens: Counted input or byte fallback, including the protocol allowance.
        output_tokens: Enforced per-request generation cap.
        retries: SDK attempts that could incur unreturned usage.
    Returns:
        Conservative admission estimate; observed cost is recorded separately.
    """
    input_price = max(
        max(p.input_usd_per_million, p.cache_write_usd_per_million or 0) for p in spec.pricing
    )
    output_price = max(p.output_usd_per_million for p in spec.pricing)
    return (input_tokens * input_price + output_tokens * output_price) * (retries + 1) / 1_000_000


@dataclass(frozen=True)
class Reservation:
    """Admission estimate and its basis, never substituted for billed usage."""

    usd: float
    input_tokens: int
    method: Literal["counted", "bytes", "offline"]


async def estimate_request(
    model: Model | None,
    config: AnalystConfig,
    spec: ModelSpec,
    messages: list[ModelMessage],
    settings: ModelSettings | None,
    parameters: ModelRequestParameters,
) -> Reservation:
    """Count input with the injected model, retaining a conservative fallback.

    Args:
        model: Shared provider with a free token-counting endpoint, if supported.
        config, spec: Admission policy and pinned prices.
        messages, settings, parameters: The exact generation request contract.
    Returns:
        Count plus safety allowance, full output cap, and all SDK attempts reserved.
    """
    encoded = TypeAdapter(list[ModelMessage]).dump_json(messages)
    tokens = len(encoded) + len(str(asdict(parameters)).encode())
    method: Literal["counted", "bytes"] = "bytes"
    if config.count_input_tokens and model is not None:
        try:
            timeout = config.token_count_timeout_seconds or config.request_timeout_seconds
            async with asyncio.timeout(timeout):
                usage = await model.count_tokens(messages, settings, parameters)
            if usage.input_tokens > 0:
                tokens, method = usage.input_tokens, "counted"
        except (NotImplementedError, ModelAPIError, OSError, TimeoutError):
            pass
    tokens += config.request_overhead_tokens
    output = (settings or {}).get("max_tokens") or config.max_output_tokens
    return Reservation(request_bound(spec, tokens, output, config.sdk_retries), tokens, method)
