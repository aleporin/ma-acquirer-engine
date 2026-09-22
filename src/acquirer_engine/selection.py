"""Prepare the target, feedback-adjusted ranking, and bounded evidence packs.

Owns: Product input selection before any narrative generation.
Does not own: Changing backtest baselines or provider execution.
"""

from dataclasses import dataclass
from pathlib import Path

from acquirer_engine.data.loader import load_transactions
from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.errors import DataError
from acquirer_engine.evidence.ids import stat_id
from acquirer_engine.evidence.pack import CorePack, Statistic, build_core_pack
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.feedback.ranking import FeedbackPolicy, apply_feedback
from acquirer_engine.feedback.state import FeedbackState, load_feedback
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.settings import load_feedback_policy
from acquirer_engine.target_input import TargetOverrides, resolve_target


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


def prepare_selection(
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
