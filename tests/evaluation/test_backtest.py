"""Prevent label and temporal leakage in ranking evaluation.

Owns: Training scope, query attributes, baselines, and cold-start accounting.
Does not own: Tuning scores from test outcomes.
"""

from acquirer_engine.ranking.config import BacktestConfig
from acquirer_engine.settings import Settings
from evals.ranking.backtest import run_backtest, split_transactions, target_from_transaction
from tests.fixtures.ranking import transaction


def config() -> BacktestConfig:
    """Keep synthetic resampling small and deterministic."""
    return BacktestConfig(
        train_end_year=2021,
        test_end_year=2024,
        bootstrap_samples=50,
        confidence=0.95,
        stability_runs=5,
        minimum_conviction_levels=2,
    )


def test_temporal_split_and_unseen_buyers_remain_misses(settings: Settings) -> None:
    rows = [
        transaction(1, deal_year=2020),
        transaction(2, deal_year=2021, acquirer="Buyer B"),
        transaction(3, deal_year=2022, acquirer="Unseen"),
        transaction(4, deal_year=2024, acquirer="Buyer A"),
    ]
    report = run_backtest(rows, settings.scoring, config(), seed=42)
    assert report.train_rows == 2
    assert report.test_rows == 2
    assert report.unseen_labels == 1
    assert report.candidate_count == 2
    assert report.metrics["ranker"]["recall_at_k"] == 0.5
    assert set(report.lift) == {"global_popularity", "sector_popularity", "random"}
    assert set(report.ablations) == set(settings.scoring.weights)


def test_future_changes_cannot_change_fitted_state_or_earlier_queries(settings: Settings) -> None:
    rows = [
        transaction(1, deal_year=2020),
        transaction(2, deal_year=2022, acquirer="Buyer A"),
        transaction(3, deal_year=2024, acquirer="Future"),
    ]
    changed = rows[:2] + [
        transaction(3, deal_year=2024, acquirer="Other", sector="New", deal_size_mm=9000)
    ]
    left = run_backtest(rows, settings.scoring, config(), seed=7)
    right = run_backtest(changed, settings.scoring, config(), seed=7)
    assert left.training_sha256 == right.training_sha256
    assert left.cases[0] == right.cases[0]
    train, test = split_transactions(rows, config())
    assert {row.deal_year for row in train} == {2020}
    assert {row.deal_year for row in test} == {2022, 2024}


def test_query_omits_buyer_outcome_and_post_deal_rationale() -> None:
    original = transaction(1)
    changed = transaction(
        1,
        acquirer="Changed",
        outcome="Terminated",
        days_to_close=None,
        strategic_rationale_tags="Unique Insight",
        deal_type="SPAC Merger",
    )
    assert target_from_transaction(original) == target_from_transaction(changed)
    assert target_from_transaction(original).tags == ()


def test_backtest_is_independent_of_input_order(settings: Settings) -> None:
    rows = [
        transaction(1, deal_year=2020),
        transaction(2, deal_year=2021, acquirer="Buyer B"),
        transaction(3, deal_year=2022, acquirer="Buyer A"),
    ]
    assert run_backtest(rows, settings.scoring, config(), seed=7) == run_backtest(
        rows[::-1], settings.scoring, config(), seed=7
    )
