"""Run analyst pages with a shared-prefix warm-up and bounded fan-out.

Owns: Task scheduling and stable input-order result collection.
Does not own: Provider construction, repair, or ranking.
"""

import asyncio

from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.analyst import analyze_one
from acquirer_engine.llm.results import PageResult


async def run_analysts(packs: list[CorePack], deps: Deps) -> list[PageResult]:
    """Start other pages after the first response primes the shared prefix.

    Args:
        packs: Ranked buyer packs in output order.
        deps: Shared clients, cache, ledger, logger, and concurrency policy.
    Returns:
        Results in ranking order, including explicit failures.
    """
    if not packs:
        return []
    runtime = deps.runtime
    assert runtime is not None
    runtime.model.first_response.clear()
    semaphore = asyncio.Semaphore(deps.settings.analyst.concurrency)

    async def bounded(pack: CorePack) -> PageResult:
        async with semaphore:
            return await analyze_one(pack, deps)

    first = asyncio.create_task(bounded(packs[0]))
    warm = asyncio.create_task(runtime.model.first_response.wait())
    try:
        await asyncio.wait((first, warm), return_when=asyncio.FIRST_COMPLETED)
        return list(await asyncio.gather(first, *(bounded(pack) for pack in packs[1:])))
    finally:
        warm.cancel()
        await asyncio.gather(warm, return_exceptions=True)
        if not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
