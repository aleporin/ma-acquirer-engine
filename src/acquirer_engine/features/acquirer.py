"""Fit immutable histories and dataset-wide features.

Owns: Cutoff enforcement, outcome policy, and descriptive buyer statistics.
Does not own: Query-specific scores or test-period information.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from acquirer_engine.data.schema import AcquirerType, Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.features.similarity import sector_similarity
from acquirer_engine.features.tags import idf_weights
from acquirer_engine.ranking.config import RankingConfig


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
