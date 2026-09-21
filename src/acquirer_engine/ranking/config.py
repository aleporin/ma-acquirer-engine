"""Validate the ranking policy before any features are fitted.

Owns: Tunable scoring, target, and data-quality parameters.
Does not own: Selecting parameters from holdout results.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator

type FeatureName = Literal[
    "sector_fit",
    "size_fit",
    "recency",
    "completion",
    "profile_fit",
    "tag_fit",
    "geography_fit",
    "deal_type_fit",
]
type UnitFloat = Annotated[float, Field(ge=0, le=1)]


class TargetDefaults(BaseModel):
    """Declared assumptions used to construct the assignment query."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    sector: str
    deal_size_mm: PositiveFloat
    geography: str
    ownership: str
    margin_quantile: UnitFloat
    tags: tuple[str, ...]


class RankingConfig(BaseModel):
    """A fixed policy chosen before the temporal holdout is evaluated."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    weights: dict[FeatureName, UnitFloat]
    size_band: tuple[PositiveFloat, PositiveFloat]
    soft_size_band: tuple[PositiveFloat, PositiveFloat]
    reference_year: PositiveInt
    recency_half_life: PositiveFloat
    activity_scale: PositiveFloat
    prior_strength: PositiveFloat
    adjacent_discount: UnitFloat
    coactivity_weight: UnitFloat
    neutral_value: UnitFloat
    relevant_similarity: UnitFloat
    high_score: UnitFloat
    medium_score: UnitFloat
    high_min_relevant: PositiveInt
    broad_geographies: tuple[str, ...]
    weak_deal_types: tuple[str, ...]
    multiple_tolerance: PositiveFloat
    margin_tolerance: PositiveFloat
    top_k: PositiveInt
    default_target: TargetDefaults

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        """Require complete weights and ordered bands without normalizing silently."""
        expected = {
            "sector_fit",
            "size_fit",
            "recency",
            "completion",
            "profile_fit",
            "tag_fit",
            "geography_fit",
            "deal_type_fit",
        }
        if set(self.weights) != expected or abs(sum(self.weights.values()) - 1) > 1e-9:
            raise ValueError("All feature weights must be present and sum to one")
        low, high = self.size_band
        soft_low, soft_high = self.soft_size_band
        if not soft_low < low < 1 < high < soft_high:
            raise ValueError("Size bands must expand around the target")
        if self.medium_score >= self.high_score:
            raise ValueError("Conviction thresholds must be ordered")
        return self
