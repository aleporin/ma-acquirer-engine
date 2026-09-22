"""Reserve run spending before concurrent requests and retain uncertain charges.

Owns: Admission, shared reservations, and conservative request cost bounds.
Does not own: Provider billing reconciliation or accepting invalid output.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from acquirer_engine.errors import BudgetExceeded
from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.settings import ModelSpec


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
