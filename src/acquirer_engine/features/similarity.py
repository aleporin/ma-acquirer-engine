"""Learn sector adjacency from observed sponsor activity and profiles.

Owns: A symmetric, discounted sector similarity matrix fitted from history.
Does not own: Hand-written sector neighborhoods or target ranking.
"""

import math
from collections import Counter
from collections.abc import Sequence
from statistics import median

from acquirer_engine.data.schema import Transaction
from acquirer_engine.ranking.config import RankingConfig


def _centroid(rows: Sequence[Transaction]) -> tuple[float, float, float]:
    return (
        median(row.ebitda_margin_pct for row in rows),
        median(math.log(row.ev_ebitda_multiple) for row in rows),
        median(math.log(row.deal_size_mm) for row in rows),
    )


def _cosine(left: list[int], right: list[int]) -> float:
    denominator = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right, strict=True)) / denominator if denominator else 0


def sector_similarity(
    rows: Sequence[Transaction], config: RankingConfig
) -> dict[tuple[str, str], float]:
    """Fit co-activity cosine and normalized financial-profile distance.

    Args:
        rows: Non-rumored training history only.
        config: Blend and adjacency discount.
    Returns:
        Unit diagonal and discounted, symmetric off-diagonal scores.
    """
    sectors = sorted({row.sector for row in rows})
    sponsors = sorted({row.acquirer for row in rows if row.acquirer_type == "Financial Sponsor"})
    counts = Counter(
        (row.sector, row.acquirer) for row in rows if row.acquirer_type == "Financial Sponsor"
    )
    centers = {
        sector: _centroid([row for row in rows if row.sector == sector]) for sector in sectors
    }
    scales = [
        max(c[i] for c in centers.values()) - min(c[i] for c in centers.values()) for i in range(3)
    ]
    result = {}
    for left in sectors:
        for right in sectors:
            cosine = _cosine(
                [counts[left, s] for s in sponsors], [counts[right, s] for s in sponsors]
            )
            distances = [
                abs(centers[left][i] - centers[right][i]) / scale if scale else 0
                for i, scale in enumerate(scales)
            ]
            profile = math.exp(-sum(distances) / len(distances))
            blend = config.coactivity_weight * cosine + (1 - config.coactivity_weight) * profile
            result[left, right] = 1.0 if left == right else config.adjacent_discount * blend
    return result
