"""Define bounded ranking hypotheses and conservative buyer adjustments.

Owns: Experiment policy, complete type profiles, and normalized feature weights.
Does not own: Changing the shipped ranker or interpreting benchmark outcomes.
"""

import math
from collections import Counter
from pathlib import Path
from statistics import fmean, pstdev
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    ValidationError,
    model_validator,
)

from acquirer_engine.data import AcquirerType
from acquirer_engine.errors import EvaluationError
from acquirer_engine.ranking.config import FeatureName, RankingConfig
from acquirer_engine.ranking.features import AcquirerHistory


class ExperimentPolicy(BaseModel):
    """A frozen selection protocol independent of production configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    proposal_cutoff: PositiveInt
    selection_years: tuple[PositiveInt, ...]
    test_end_year: PositiveInt
    seed: int
    bootstrap_samples: PositiveInt
    confidence: Annotated[float, Field(gt=0, lt=1)]
    buyer_prior_deals: PositiveFloat
    buyer_strength: Annotated[float, Field(gt=0, le=1)]
    min_multiplier: PositiveFloat
    max_multiplier: PositiveFloat
    max_candidates: PositiveInt
    prompt_file: str
    max_output_tokens: PositiveInt
    max_run_usd: PositiveFloat
    request_timeout_seconds: PositiveFloat
    run_timeout_seconds: PositiveFloat
    max_retries: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def ordered_protocol(self) -> Self:
        """Keep proposal, selection, and benchmark periods disjoint."""
        years = self.selection_years
        if not years or tuple(sorted(set(years))) != years:
            raise ValueError("Selection years must be nonempty, unique and ordered")
        if not self.proposal_cutoff < years[0] <= years[-1] < self.test_end_year:
            raise ValueError("Proposal, selection and benchmark periods must be ordered")
        if not self.min_multiplier <= 1 <= self.max_multiplier:
            raise ValueError("Multiplier bounds must include the unchanged control")
        return self


class Candidate(BaseModel):
    """A hypothesis with a complete multiplier vector for each buyer type."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    explanation: Annotated[str, Field(min_length=1)]
    multipliers: dict[AcquirerType, dict[FeatureName, PositiveFloat]]


def load_policy(path: Path) -> ExperimentPolicy:
    """Read the frozen experiment policy, rejecting invalid local input."""
    try:
        return ExperimentPolicy.model_validate(yaml.safe_load(path.read_text("utf-8")))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise EvaluationError("Invalid ranking experiment policy") from error


def shared_candidate(config: RankingConfig) -> Candidate:
    """Create the unchanged control independently of proposed alternatives."""
    return Candidate(
        name="shared",
        explanation="Shipped shared weights without buyer-specific adjustments.",
        multipliers={
            kind: dict.fromkeys(config.weights, 1.0) for kind in ("Financial Sponsor", "Strategic")
        },
    )


def validate_candidates(
    candidates: list[Candidate], policy: ExperimentPolicy, config: RankingConfig
) -> None:
    """Require bounded, complete, uniquely named profiles before any evaluation.

    Raises:
        EvaluationError: Candidate inventory or feature multipliers violate policy.
    """
    if not 0 < len(candidates) <= policy.max_candidates:
        raise EvaluationError("Proposal candidate count exceeds the frozen policy")
    if len({c.name for c in candidates}) != len(candidates):
        raise EvaluationError("Candidate names must be unique")
    for candidate in candidates:
        if set(candidate.multipliers) != {"Financial Sponsor", "Strategic"}:
            raise EvaluationError("Every candidate must specify both buyer types")
        for weights in candidate.multipliers.values():
            if set(weights) != set(config.weights):
                raise EvaluationError("Every candidate must specify all scoring features")
            if not all(
                policy.min_multiplier <= x <= policy.max_multiplier for x in weights.values()
            ):
                raise EvaluationError("Proposed multiplier is outside the frozen bounds")


def concentrations(buyer: AcquirerHistory) -> dict[FeatureName, float]:
    """Measure concentration from observed purchases, without inferring mandates."""
    counts = Counter(row.sector for row in buyer.rows)
    margins = [row.ebitda_margin_pct for row in buyer.rows]
    return {
        "sector_fit": sum((n / buyer.deal_count) ** 2 for n in counts.values()),
        "size_fit": 1 / (1 + pstdev(math.log(r.deal_size_mm) for r in buyer.rows)),
        "profile_fit": 1 / (1 + pstdev(margins) / fmean(margins)),
    }


def validate_proposals(
    candidates: list[Candidate], policy: ExperimentPolicy, config: RankingConfig
) -> None:
    """Reserve baseline identifiers before accepting external hypotheses."""
    validate_candidates(candidates, policy, config)
    reserved = {"shared", "global_popularity", "sector_popularity", "random"}
    if any(candidate.name in reserved for candidate in candidates):
        raise EvaluationError("Hypothesis name is reserved for a comparison method")


def buyer_weights(
    candidate: Candidate,
    buyer: AcquirerHistory,
    config: RankingConfig,
    policy: ExperimentPolicy,
    *,
    strength: float,
) -> dict[FeatureName, float]:
    """Shrink optional concentration tilts toward a normalized type default.

    Args:
        candidate: Previously validated hypothesis.
        buyer: Past eligible history only.
        config, policy: Frozen feature weights and experiment parameters.
        strength: Zero for type-only weighting, or the configured buyer tilt.
    Returns:
        Nonnegative weights summing to one; no production object is changed.
    """
    reliability = buyer.deal_count / (buyer.deal_count + policy.buyer_prior_deals)
    concentration = concentrations(buyer) if strength else {}
    weights = {
        feature: weight
        * candidate.multipliers[buyer.acquirer_type][feature]
        * (1 + strength * reliability * concentration.get(feature, 0))
        for feature, weight in config.weights.items()
    }
    total = sum(weights.values())
    return {feature: weight / total for feature, weight in weights.items()}
