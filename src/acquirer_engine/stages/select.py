"""Select ranked buyers and their evidence before narrative generation.

Owns: Target precedence, feedback application, ranking, and bounded core packs.
Does not own: Scoring mathematics, holdout evaluation, or provider execution.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, ValidationError

from acquirer_engine.data import Transaction, load_transactions
from acquirer_engine.deps import Deps
from acquirer_engine.errors import DataError
from acquirer_engine.evidence.pack import CorePack, Statistic, build_core_pack, stat_id
from acquirer_engine.feedback.ranking import FeedbackPolicy, apply_feedback
from acquirer_engine.feedback.state import FeedbackState, load_feedback
from acquirer_engine.ranking.config import RankingConfig
from acquirer_engine.ranking.features import fit_features
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.ranking.target import TargetProfile
from acquirer_engine.settings import load_feedback_policy


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


@dataclass(frozen=True)
class Selection:
    """Frozen product inputs, including the user feedback that affected ranking."""

    history: tuple[Transaction, ...]
    packs: tuple[CorePack, ...]
    feedback: FeedbackState
    feedback_policy: FeedbackPolicy


def _penalty_evidence(pack: CorePack, max_tokens: int) -> CorePack:
    base = sum(signal.contribution for signal in pack.ranking.signals.values())
    multiplier = pack.ranking.score / base if base else 1.0
    statistics = tuple(
        Statistic(evidence_id=stat_id(metric, pack.ranking.acquirer), metric=metric, value=value)
        for metric, value in (("base_score", base), ("feedback_multiplier", multiplier))
    )
    pack = pack.model_copy(update={"statistics": pack.statistics + statistics})
    while pack.token_upper_bound > max_tokens and pack.deals:
        pack = pack.model_copy(update={"deals": pack.deals[:-1], "truncated": True})
    if pack.token_upper_bound > max_tokens:
        raise DataError("Feedback evidence exceeds the configured core token cap")
    return pack


def select_buyers(
    root: Path,
    deps: Deps,
    *,
    target_file: Path | None = None,
    overrides: TargetOverrides | None = None,
) -> Selection:
    """Select buyers after applying validated target input and saved feedback.

    Args:
        root: Repository with data, configuration, and optional local state.
        deps: Run settings and logger.
        target_file, overrides: Optional target values, with flags taking precedence.
    Returns:
        Eligible history, ordered packs, and explicit selection provenance.
    Raises:
        DataError: Invalid input, saved feedback, or no remaining candidates.
    """
    rows = load_transactions(root / "data/ma_transactions_500.csv")
    config = deps.settings.scoring
    fitted = fit_features(rows, config, reference_year=config.reference_year)
    history = tuple(row for buyer in fitted.acquirers.values() for row in buyer.rows)
    target = resolve_target(history, config, target_file, overrides)
    feedback = load_feedback(root / "state/feedback.json")
    policy = load_feedback_policy(root / "config")
    ranked = apply_feedback(
        rank_acquirers(fitted, target, config), fitted, feedback, policy.similarity_penalty, config
    )[: config.top_k]
    if not ranked:
        raise DataError("No acquirers remain after applying feedback")
    packs = [
        build_core_pack(fitted.acquirers[item.acquirer], item, target, deps.settings.evidence.pack)
        for item in ranked
    ]
    if feedback.flags:
        packs = [_penalty_evidence(pack, deps.settings.evidence.pack.max_tokens) for pack in packs]
    deps.logger.info(
        "ranking_computed",
        stage="ranking",
        rows=len(rows),
        candidates=len(packs),
        exclusions=len(feedback.flags),
    )
    return Selection(history, tuple(packs), feedback, policy)
