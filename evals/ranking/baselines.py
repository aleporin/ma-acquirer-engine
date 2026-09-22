"""Rank the same candidate universe with fixed baseline methods.

Owns: Global popularity, sector popularity, and seeded random ordering.
Does not own: Training on holdout labels.
"""

from random import Random

from acquirer_engine.ranking.features import FittedFeatures


def baseline_rankings(
    fitted: FittedFeatures, sector: str, *, seed: int, query_id: str
) -> dict[str, list[str]]:
    """Construct three rankings from the exact fitted candidate universe.

    Args:
        fitted: Training-only candidate histories.
        sector: Query sector.
        seed: Shared run seed.
        query_id: Stable query identity for order-independent shuffling.
    Returns:
        Complete rankings with deterministic popularity ties.
    """
    names = sorted(fitted.acquirers)
    counts = {name: fitted.acquirers[name].deal_count for name in names}
    sectors = {
        name: sum(row.sector == sector for row in fitted.acquirers[name].rows) for name in names
    }
    shuffled = names.copy()
    Random(f"{seed}:{query_id}").shuffle(shuffled)
    return {
        "global_popularity": sorted(names, key=lambda name: (-counts[name], name.casefold(), name)),
        "sector_popularity": sorted(
            names, key=lambda name: (-sectors[name], -counts[name], name.casefold(), name)
        ),
        "random": shuffled,
    }
