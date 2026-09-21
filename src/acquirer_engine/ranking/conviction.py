"""Assign conviction from score and evidence density.

Owns: Deterministic levels from fixed configuration.
Does not own: Buyer quotas or forcing a distribution of levels.
"""

from typing import Literal

from acquirer_engine.ranking.config import RankingConfig

type Conviction = Literal["High", "Medium", "Low"]


def conviction(score: float, relevant_deals: int, config: RankingConfig) -> Conviction:
    """Apply score boundaries and require evidence for high conviction.

    Args:
        score: Computed score in the unit interval.
        relevant_deals: Direct or sufficiently similar historical transactions.
        config: Ordered score boundaries and evidence requirement.
    Returns:
        A level independently of every other buyer's assigned level.
    """
    if score >= config.high_score and relevant_deals >= config.high_min_relevant:
        return "High"
    return "Medium" if score >= config.medium_score else "Low"
