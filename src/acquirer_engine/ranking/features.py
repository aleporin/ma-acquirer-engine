"""Fit buyer histories and shared ranking features from eligible transactions.

Owns: Cutoff enforcement, tag weights, sector similarity, and buyer aggregates.
Does not own: Target-specific scores, holdout evaluation, or narrative generation.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from acquirer_engine.data import AcquirerType, Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.ranking.config import RankingConfig


def parse_tags(value: str) -> frozenset[str]:
    """Return unique nonempty pipe-delimited tags.

    Args:
        value: Validated CSV tag string.
    Returns:
        Unique trimmed tags.
    """
    return frozenset(tag.strip() for tag in value.split("|") if tag.strip())


def idf_weights(rows: Sequence[Transaction]) -> dict[str, float]:
    """Compute smoothed IDF; a ubiquitous tag has zero weight.

    Args:
        rows: Training transactions only.
    Returns:
        Deterministically ordered tag weights.
    """
    counts = Counter(tag for row in rows for tag in parse_tags(row.strategic_rationale_tags))
    return {tag: math.log((len(rows) + 1) / (counts[tag] + 1)) for tag in sorted(counts)}


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


@dataclass(frozen=True)
class AcquirerHistory:
    """Observed activity and canonical closed-deal valuation summaries."""

    name: str
    acquirer_type: AcquirerType
    rows: tuple[Transaction, ...]
    deal_count: int
    size_min: float
    size_max: float
    recency_count: float
    completion_rate: float | None
    median_ev_ebitda: float | None
    median_ev_revenue: float | None
    platform_sectors: tuple[str, ...]


@dataclass(frozen=True)
class FittedFeatures:
    """Only information available at the chosen history cutoff."""

    acquirers: dict[str, AcquirerHistory]
    similarity: dict[tuple[str, str], float]
    tag_idf: dict[str, float]
    training_ids: tuple[str, ...]
    reference_year: int


def _history(
    name: str, rows: tuple[Transaction, ...], year: int, half_life: float
) -> AcquirerHistory:
    closed = [row for row in rows if row.outcome == "Closed"]
    resolved = [row for row in rows if row.outcome in {"Closed", "Withdrawn", "Terminated"}]
    return AcquirerHistory(
        name=name,
        acquirer_type=rows[0].acquirer_type,
        rows=rows,
        deal_count=len(rows),
        size_min=min(row.deal_size_mm for row in rows),
        size_max=max(row.deal_size_mm for row in rows),
        recency_count=sum(0.5 ** ((year - row.deal_year) / half_life) for row in rows),
        completion_rate=len(closed) / len(resolved) if resolved else None,
        median_ev_ebitda=median(row.ev_ebitda_multiple for row in closed) if closed else None,
        median_ev_revenue=median(row.ev_revenue_multiple for row in closed) if closed else None,
        platform_sectors=tuple(
            sorted({row.sector for row in rows if row.deal_type == "Platform Investment"})
        ),
    )


def fit_features(
    rows: Sequence[Transaction], config: RankingConfig, *, reference_year: int
) -> FittedFeatures:
    """Fit every transform and buyer identity from eligible history only.

    Args:
        rows: Validated transactions, possibly including future observations.
        config: Fixed scoring policy.
        reference_year: Latest year visible to fitting and recency calculations.
    Returns:
        History features excluding future and rumored deals.
    Raises:
        DataError: No eligible historical transactions remain.
    """
    history = tuple(
        sorted(
            (r for r in rows if r.deal_year <= reference_year and r.outcome != "Rumored"),
            key=lambda row: row.transaction_id,
        )
    )
    if not history:
        raise DataError("No eligible historical transactions")
    buyers = {
        name: _history(
            name,
            tuple(r for r in history if r.acquirer == name),
            reference_year,
            config.recency_half_life,
        )
        for name in sorted({row.acquirer for row in history})
    }
    return FittedFeatures(
        buyers,
        sector_similarity(history, config),
        idf_weights(history),
        tuple(row.transaction_id for row in history),
        reference_year,
    )
