"""Evaluate a frozen temporal ranking model.

Owns: Temporal splitting, label-free queries, and baseline/ablation execution.
Does not own: Hyperparameter search or removing unrecoverable test labels.
"""

import hashlib
from collections.abc import Sequence

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import EvaluationError
from acquirer_engine.features.acquirer import FittedFeatures, fit_features
from acquirer_engine.ranking.config import BacktestConfig, RankingConfig
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.ranking.target import TargetProfile
from evals.ranking.baselines import baseline_rankings
from evals.ranking.report import BacktestReport, CaseResult, aggregate_cases


def split_transactions(
    rows: Sequence[Transaction], config: BacktestConfig
) -> tuple[list[Transaction], list[Transaction]]:
    """Split by announcement year, without consulting outcomes or labels.

    Args:
        rows: Validated transactions.
        config: Fixed training cutoff and holdout end.
    Returns:
        Identity-sorted training and test populations.
    """
    ordered = sorted(rows, key=lambda row: row.transaction_id)
    return (
        [row for row in ordered if row.deal_year <= config.train_end_year],
        [row for row in ordered if config.train_end_year < row.deal_year <= config.test_end_year],
    )


def target_from_transaction(row: Transaction) -> TargetProfile:
    """Extract only query-observable target attributes.

    Args:
        row: One held-out transaction.
    Returns:
        Target without buyer, outcome, deal type, or post-deal rationale tags.
    """
    return TargetProfile(
        sector=row.sector,
        deal_size_mm=row.deal_size_mm,
        ebitda_margin_pct=row.ebitda_margin_pct,
        geography=row.geography,
        ownership=row.target_ownership_pre,
        tags=(),
    )


def _case(
    row: Transaction, fitted: FittedFeatures, scoring: RankingConfig, seed: int
) -> CaseResult:
    target = target_from_transaction(row)
    methods = baseline_rankings(fitted, target.sector, seed=seed, query_id=row.transaction_id)
    methods["ranker"] = [item.acquirer for item in rank_acquirers(fitted, target, scoring)]
    for feature in scoring.weights:
        methods[f"without_{feature}"] = [
            item.acquirer for item in rank_acquirers(fitted, target, scoring, drop=feature)
        ]
    return CaseResult(
        transaction_id=row.transaction_id,
        ranks={
            name: ranking.index(row.acquirer) + 1 if row.acquirer in ranking else None
            for name, ranking in methods.items()
        },
    )


def run_backtest(
    rows: Sequence[Transaction], scoring: RankingConfig, config: BacktestConfig, *, seed: int
) -> BacktestReport:
    """Measure a frozen ranker against baselines on every held-out transaction.

    Args:
        rows: Validated source data.
        scoring: Policy fixed before inspecting holdout results.
        config: Temporal split and uncertainty policy.
        seed: Bootstrap and random-baseline seed.
    Returns:
        Metrics, paired intervals, ablations, and explicit cold-start counts.
    Raises:
        EvaluationError: The split lacks training or test observations.
    """
    train, test = split_transactions(rows, config)
    if not train or not test:
        raise EvaluationError("Backtest requires nonempty training and holdout periods")
    fitted = fit_features(train, scoring, reference_year=config.train_end_year)
    cases = [_case(row, fitted, scoring, seed) for row in test]
    metrics, lift = aggregate_cases(cases, scoring.top_k, config, seed)
    encoded = "\n".join(
        row.model_dump_json() for row in train if row.transaction_id in fitted.training_ids
    ).encode()
    return BacktestReport(
        train_rows=len(train),
        eligible_train_rows=len(fitted.training_ids),
        test_rows=len(test),
        candidate_count=len(fitted.acquirers),
        unseen_labels=sum(row.acquirer not in fitted.acquirers for row in test),
        training_sha256=hashlib.sha256(encoded).hexdigest(),
        seed=seed,
        train_end_year=config.train_end_year,
        test_end_year=config.test_end_year,
        bootstrap_samples=config.bootstrap_samples,
        confidence=config.confidence,
        metrics={
            name: values for name, values in metrics.items() if not name.startswith("without_")
        },
        lift=lift,
        ablations={name: metrics[f"without_{name}"] for name in scoring.weights},
        cases=cases,
    )
