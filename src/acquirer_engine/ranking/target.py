"""Represent the target independently of its eventual acquirer.

Owns: Typed query profiles and explicit assignment assumptions.
Does not own: Reading buyer labels or learning from held-out transactions.
"""

from collections.abc import Sequence
from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.ranking.config import RankingConfig


class TargetProfile(BaseModel):
    """Only attributes observable about a target at query time."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    sector: Annotated[str, Field(min_length=1)]
    deal_size_mm: PositiveFloat
    ebitda_margin_pct: Annotated[float, Field(gt=0, le=100)]
    geography: Annotated[str, Field(min_length=1)]
    ownership: Annotated[str, Field(min_length=1)]
    tags: tuple[str, ...]

    def size_band(self, config: RankingConfig) -> tuple[float, float]:
        """Scale the configured band around this target's EV.

        Args:
            config: Relative EV bands.
        Returns:
            Lower and upper enterprise values in millions.
        """
        low, high = config.size_band
        return low * self.deal_size_mm, high * self.deal_size_mm


def assignment_target(rows: Sequence[Transaction], config: RankingConfig) -> TargetProfile:
    """Translate the configured assumptions into a numeric target.

    Args:
        rows: Eligible history used to estimate the target's margin.
        config: Target assumptions including a sector margin quantile.
    Returns:
        Target with no acquirer identity or outcome fields.
    Raises:
        DataError: The configured target sector has no historical margins.
    """
    defaults = config.default_target
    margins = [row.ebitda_margin_pct for row in rows if row.sector == defaults.sector]
    if not margins:
        raise DataError("Target sector has no historical margin observations")
    return TargetProfile(
        sector=defaults.sector,
        deal_size_mm=defaults.deal_size_mm,
        ebitda_margin_pct=float(pd.Series(margins).quantile(defaults.margin_quantile)),
        geography=defaults.geography,
        ownership=defaults.ownership,
        tags=defaults.tags,
    )
