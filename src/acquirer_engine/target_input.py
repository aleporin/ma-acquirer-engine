"""Resolve target assumptions from defaults, a YAML file, and CLI overrides.

Owns: Typed target input and measurement of omitted margins.
Does not own: Fitting buyer features or selecting candidates.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, ValidationError

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.ranking.config import RankingConfig
from acquirer_engine.ranking.target import TargetProfile


class TargetOverrides(BaseModel):
    """Only explicitly supplied values replace configured target assumptions."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, str_strip_whitespace=True
    )
    sector: Annotated[str, Field(min_length=1)] | None = None
    deal_size_mm: PositiveFloat | None = None
    ebitda_margin_pct: Annotated[float, Field(gt=0, le=100)] | None = None
    geography: Annotated[str, Field(min_length=1)] | None = None
    ownership: Annotated[str, Field(min_length=1)] | None = None
    tags: tuple[Annotated[str, Field(min_length=1)], ...] | None = None


def resolve_target(
    rows: Sequence[Transaction],
    config: RankingConfig,
    path: Path | None = None,
    overrides: TargetOverrides | None = None,
) -> TargetProfile:
    """Apply file then CLI values, measuring any omitted margin for that sector.

    Args:
        rows: Eligible history at the scoring cutoff.
        config: Default assumptions and margin quantile.
        path: Optional partial target YAML file.
        overrides: Explicit CLI values, taking precedence over the file.
    Returns:
        Validated target used unchanged throughout the run.
    Raises:
        DataError: Invalid YAML or an unobserved sector without an explicit margin.
    """
    values = config.default_target.model_dump(exclude={"margin_quantile"})
    if path is not None:
        try:
            parsed = TargetOverrides.model_validate(yaml.safe_load(path.read_text("utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
            raise DataError(f"Invalid target file: {path.name}") from error
        values.update(parsed.model_dump(exclude_none=True))
    if overrides is not None:
        values.update(overrides.model_dump(exclude_none=True))
    if "ebitda_margin_pct" not in values:
        margins = [r.ebitda_margin_pct for r in rows if r.sector == values["sector"]]
        if not margins:
            raise DataError("No historical margins for target sector; supply --margin explicitly")
        values["ebitda_margin_pct"] = float(
            pd.Series(margins).quantile(config.default_target.margin_quantile)
        )
    return TargetProfile.model_validate(values)
