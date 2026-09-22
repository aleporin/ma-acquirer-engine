"""Compute overlap and rank movement between two target shortlists.

Owns: Comparison arithmetic with an explicit missing-rank representation.
Does not own: Model interpretation or fitting ranking features.
"""

from pydantic import BaseModel, ConfigDict

from acquirer_engine.data.schema import AcquirerType
from acquirer_engine.ranking.conviction import Conviction
from acquirer_engine.ranking.scorer import RankedAcquirer
from acquirer_engine.ranking.target import TargetProfile


class ComparisonRow(BaseModel):
    """Positive rank_delta means the buyer ranks higher for target B."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    acquirer: str
    acquirer_type: AcquirerType
    rank_a: int | None
    rank_b: int | None
    score_a: float | None
    score_b: float | None
    conviction_a: Conviction | None
    conviction_b: Conviction | None
    rank_delta: int | None


class ComparisonData(BaseModel):
    """Only computed target and ranking facts enter the summary request."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target_a: TargetProfile
    target_b: TargetProfile
    rows: tuple[ComparisonRow, ...]
    overlap: tuple[str, ...]
    overlap_fraction: float


def compare_rankings(
    target_a: TargetProfile,
    target_b: TargetProfile,
    left: list[RankedAcquirer],
    right: list[RankedAcquirer],
) -> ComparisonData:
    """Compare named candidates without pretending an absent buyer has a rank.

    Args:
        target_a, target_b: Resolved target assumptions.
        left, right: Already selected, ordered shortlists.
    Returns:
        A-first stable union, shared buyers, and rank A minus rank B deltas.
    """
    a = {buyer.acquirer: (rank, buyer) for rank, buyer in enumerate(left, 1)}
    b = {buyer.acquirer: (rank, buyer) for rank, buyer in enumerate(right, 1)}
    names = list(dict.fromkeys([*a, *b]))
    shared = tuple(name for name in a if name in b)
    denominator = min(len(a), len(b))
    rows = tuple(
        ComparisonRow(
            acquirer=name,
            acquirer_type=(a[name] if name in a else b[name])[1].acquirer_type,
            rank_a=a[name][0] if name in a else None,
            rank_b=b[name][0] if name in b else None,
            score_a=a[name][1].score if name in a else None,
            score_b=b[name][1].score if name in b else None,
            conviction_a=a[name][1].conviction if name in a else None,
            conviction_b=b[name][1].conviction if name in b else None,
            rank_delta=a[name][0] - b[name][0] if name in a and name in b else None,
        )
        for name in names
    )
    return ComparisonData(
        target_a=target_a,
        target_b=target_b,
        rows=rows,
        overlap=shared,
        overlap_fraction=len(shared) / denominator if denominator else 0,
    )
