"""Compute bounded query-specific signals from fitted history.

Owns: Transparent feature values before regularization.
Does not own: Prior fitting, weighting, or rank ordering.
"""

import math
from statistics import fmean

from acquirer_engine.features.acquirer import AcquirerHistory, FittedFeatures
from acquirer_engine.features.tags import parse_tags
from acquirer_engine.ranking.config import FeatureName, RankingConfig
from acquirer_engine.ranking.target import TargetProfile


def _size_fit(value: float, target: float, config: RankingConfig) -> float:
    ratio = value / target
    low, high = config.size_band
    outer_low, outer_high = config.soft_size_band
    if low <= ratio <= high:
        return 1.0
    if ratio < low:
        return max(0.0, math.log(ratio / outer_low) / math.log(low / outer_low))
    return max(0.0, math.log(outer_high / ratio) / math.log(outer_high / high))


def _tag_fit(
    buyer: AcquirerHistory, target: TargetProfile, fitted: FittedFeatures, config: RankingConfig
) -> float:
    weights = {tag: fitted.tag_idf.get(tag, 0) for tag in target.tags}
    total = sum(weights.values())
    if not total:
        return config.neutral_value
    return fmean(
        sum(
            weight
            for tag, weight in weights.items()
            if tag in parse_tags(row.strategic_rationale_tags)
        )
        / total
        for row in buyer.rows
    )


def raw_signals(
    buyer: AcquirerHistory, target: TargetProfile, fitted: FittedFeatures, config: RankingConfig
) -> dict[FeatureName, float]:
    """Compute fit, activity, and execution signals from observed history.

    Args:
        buyer: One candidate's history.
        target: Query attributes, without the buyer label.
        fitted: Training-only transforms.
        config: Numeric policy and weak deal-type categories.
    Returns:
        Bounded feature values keyed by the configured feature groups.
    """
    return {
        "sector_fit": fmean(
            fitted.similarity.get((target.sector, row.sector), 0) for row in buyer.rows
        ),
        "size_fit": fmean(
            _size_fit(row.deal_size_mm, target.deal_size_mm, config) for row in buyer.rows
        ),
        "recency": 1 - math.exp(-buyer.recency_count / config.activity_scale),
        "completion": buyer.completion_rate
        if buyer.completion_rate is not None
        else config.neutral_value,
        "profile_fit": fmean(
            math.exp(-abs(math.log(row.ebitda_margin_pct / target.ebitda_margin_pct)))
            for row in buyer.rows
        ),
        "tag_fit": _tag_fit(buyer, target, fitted, config),
        "geography_fit": fmean(
            float(row.geography == target.geography or row.geography in config.broad_geographies)
            if target.geography != "Regional"
            else (1.0 if row.geography in config.broad_geographies else config.neutral_value)
            for row in buyer.rows
        ),
        "deal_type_fit": fmean(
            float(row.deal_type in config.weak_deal_types) for row in buyer.rows
        ),
    }
