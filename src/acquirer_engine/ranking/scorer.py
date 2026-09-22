"""Score buyers with explicit signals, regularization, and conviction.

Owns: Target fit, shrinkage, weighted contributions, conviction, and stable ordering.
Does not own: Historical feature fitting, policy tuning, or narrative generation.
"""

import math
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, ConfigDict

from acquirer_engine.data import AcquirerType
from acquirer_engine.ranking.config import FeatureName, RankingConfig
from acquirer_engine.ranking.features import AcquirerHistory, FittedFeatures, parse_tags
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


def shrink(observed: float, count: int, prior: float, strength: float) -> float:
    """Blend an observed signal with a prior using pseudo-observations.

    Args:
        observed: Mean signal in the unit interval.
        count: Number of supporting observations.
        prior: Empirical mean for this buyer type.
        strength: Prior pseudo-observation count.
    Returns:
        Posterior mean between the observation and prior.
    Raises:
        ValueError: Counts, strength, or bounded inputs are invalid.
    """
    if count < 0 or strength <= 0 or not 0 <= observed <= 1 or not 0 <= prior <= 1:
        raise ValueError("Invalid shrinkage arguments")
    if count == 0:
        return prior
    return (observed * count + prior * strength) / (count + strength)


class Signal(BaseModel):
    """One auditable feature from raw observation to weighted contribution."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    raw: float
    prior: float
    posterior: float
    weight: float
    contribution: float


class RankedAcquirer(BaseModel):
    """A ranked candidate with evidence density and per-feature arithmetic."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    acquirer: str
    acquirer_type: AcquirerType
    score: float
    conviction: Conviction
    relevant_deals: int
    deal_count: int
    signals: dict[FeatureName, Signal]


def _candidate(
    buyer: AcquirerHistory,
    raw: dict[FeatureName, float],
    prior: dict[FeatureName, float],
    target: TargetProfile,
    fitted: FittedFeatures,
    config: RankingConfig,
    drop: FeatureName | None,
) -> RankedAcquirer:
    weights = {name: (0 if name == drop else weight) for name, weight in config.weights.items()}
    total = sum(weights.values())
    signals = {}
    for name in sorted(weights):
        count = (
            sum(row.outcome in {"Closed", "Withdrawn", "Terminated"} for row in buyer.rows)
            if name == "completion"
            else buyer.deal_count
        )
        posterior = shrink(raw[name], count, prior[name], config.prior_strength)
        weight = weights[name] / total
        signals[name] = Signal(
            raw=raw[name],
            prior=prior[name],
            posterior=posterior,
            weight=weight,
            contribution=weight * posterior,
        )
    score = sum(signal.contribution for signal in signals.values())
    relevant = sum(
        fitted.similarity.get((target.sector, row.sector), 0) >= config.relevant_similarity
        for row in buyer.rows
    )
    return RankedAcquirer(
        acquirer=buyer.name,
        acquirer_type=buyer.acquirer_type,
        score=score,
        conviction=conviction(score, relevant, config),
        relevant_deals=relevant,
        deal_count=buyer.deal_count,
        signals=signals,
    )


def rank_acquirers(
    fitted: FittedFeatures,
    target: TargetProfile,
    config: RankingConfig,
    *,
    drop: FeatureName | None = None,
) -> list[RankedAcquirer]:
    """Score every historical candidate, with lexical ties and no type quota.

    Args:
        fitted: Eligible history and transforms fitted before any test period.
        target: Label-free query profile.
        config: Fixed weights and shrinkage policy.
        drop: Optional feature ablation; other weights are renormalized.
    Returns:
        All candidates ordered by descending score and then acquirer name.
    """
    raw = {
        name: raw_signals(buyer, target, fitted, config) for name, buyer in fitted.acquirers.items()
    }
    priors = {
        kind: {
            feature: fmean(
                values[feature]
                for name, values in raw.items()
                if fitted.acquirers[name].acquirer_type == kind
            )
            for feature in config.weights
        }
        for kind in sorted({buyer.acquirer_type for buyer in fitted.acquirers.values()})
    }
    ranked = [
        _candidate(buyer, raw[name], priors[buyer.acquirer_type], target, fitted, config, drop)
        for name, buyer in fitted.acquirers.items()
    ]
    return sorted(ranked, key=lambda item: (-item.score, item.acquirer.casefold(), item.acquirer))
