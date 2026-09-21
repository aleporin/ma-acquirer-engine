"""Reserve run spending before concurrent requests and retain uncertain charges.

Owns: Admission, shared reservations, and conservative request cost bounds.
Does not own: Provider billing reconciliation or accepting invalid output.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from acquirer_engine.errors import BudgetExceeded
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


def request_bound(spec: ModelSpec, input_bytes: int, output_tokens: int, retries: int) -> float:
    """Reserve all text bytes as tokens at the highest configured applicable price.

    Args:
        spec: Pinned pricing, including cache write prices.
        input_bytes: Serialized conversation/schema bytes plus configured protocol allowance.
        output_tokens: Enforced per-request generation cap.
        retries: SDK attempts that could incur unreturned usage.
    Returns:
        Conservative admission estimate; observed cost is recorded separately.
    """
    input_price = max(
        max(p.input_usd_per_million, p.cache_write_usd_per_million or 0) for p in spec.pricing
    )
    output_price = max(p.output_usd_per_million for p in spec.pricing)
    return (input_bytes * input_price + output_tokens * output_price) * (retries + 1) / 1_000_000
