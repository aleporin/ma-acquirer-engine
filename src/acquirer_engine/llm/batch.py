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

    results: list[PageResult] = []
    index = 0
    while index < len(packs):
        current = asyncio.create_task(bounded(packs[index]))
        warm = asyncio.create_task(runtime.model.first_response.wait())
        try:
            await asyncio.wait((current, warm), return_when=asyncio.FIRST_COMPLETED)
            if runtime.model.first_response.is_set():
                return [
                    *results,
                    *await asyncio.gather(current, *(bounded(pack) for pack in packs[index + 1 :])),
                ]
            results.append(await current)
            index += 1
        finally:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
            if not current.done():
                current.cancel()
                await asyncio.gather(current, return_exceptions=True)
    return results
