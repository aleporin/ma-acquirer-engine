"""Aggregate per-query ranking outcomes without dropping misses.

Owns: Backtest artifact schemas and paired baseline comparisons.
Does not own: Query generation or feature fitting.
"""

from statistics import fmean

from pydantic import BaseModel, ConfigDict

from acquirer_engine.ranking.config import BacktestConfig, FeatureName
from evals.ranking.metrics import Interval, metrics_at_rank, paired_lift


class CaseResult(BaseModel):
    """Observed buyer rank under each method, including unavailable labels."""

    model_config = ConfigDict(frozen=True)
    transaction_id: str
    ranks: dict[str, int | None]


class BacktestReport(BaseModel):
    """Complete measurement population, method metrics, and confidence bounds."""

    train_rows: int
    eligible_train_rows: int
    test_rows: int
    candidate_count: int
    unseen_labels: int
    training_sha256: str
    seed: int
    train_end_year: int
    test_end_year: int
    bootstrap_samples: int
    confidence: float
    metrics: dict[str, dict[str, float]]
    lift: dict[str, dict[str, Interval]]
    ablations: dict[FeatureName, dict[str, float]]
    cases: list[CaseResult]


def aggregate_cases(
    cases: list[CaseResult], k: int, config: BacktestConfig, seed: int
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, Interval]]]:
    """Aggregate all cases and compare paired method measurements.

    Args:
        cases: One result per held-out transaction, including cold starts.
        k: Retrieval cutoff.
        config: Bootstrap policy.
        seed: Reproducible resampling seed.
    Returns:
        Mean metrics by method and ranker lift over each baseline.
    """
    measurements = {
        method: [metrics_at_rank(case.ranks[method], k) for case in cases]
        for method in cases[0].ranks
    }
    names = measurements["ranker"][0]
    metrics = {
        method: {name: fmean(item[name] for item in values) for name in names}
        for method, values in measurements.items()
    }
    lift = {
        method: {
            name: paired_lift(
                [item[name] for item in measurements["ranker"]],
                [item[name] for item in measurements[method]],
                seed=seed,
                samples=config.bootstrap_samples,
                confidence=config.confidence,
            )
            for name in names
        }
        for method in ("global_popularity", "sector_popularity", "random")
    }
    return metrics, lift
