"""Protect chronological selection and transparent ranking comparisons.

Owns: Frozen selection, control parity, deterministic ties, and cold-start misses.
Does not own: Claims that exploratory results establish predictive lift.
"""

from importlib import import_module

import pytest

from acquirer_engine.errors import EvaluationError
from acquirer_engine.ranking.features import fit_features
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.settings import Settings
from evals.ranking.backtest import target_from_transaction
from tests.evaluation.test_weighting import module_and_policy
from tests.fixtures.ranking import transaction


@pytest.mark.parametrize("name", ["global_popularity", "sector_popularity", "random", "shared"])
def test_hypotheses_cannot_replace_comparison_methods(settings: Settings, name: str) -> None:
    module, policy = module_and_policy()
    experiment = import_module("evals.ranking.experiment")
    candidate = module.shared_candidate(settings.scoring).model_copy(update={"name": name})
    with pytest.raises(EvaluationError, match="reserved"):
        experiment.variants([candidate], settings.scoring, policy)


def test_shared_control_preserves_production_order(settings: Settings) -> None:
    module, policy = module_and_policy()
    experiment = import_module("evals.ranking.experiment")
    rows = [transaction(i, acquirer=f"Buyer {i}", deal_size_mm=i * 30) for i in range(1, 8)]
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    ranked = rank_acquirers(fitted, target_from_transaction(rows[0]), settings.scoring)
    candidate = module.shared_candidate(settings.scoring)
    variant = experiment.Variant(candidate=candidate, strength=0)
    assert experiment.rerank(ranked, fitted, variant, settings.scoring, policy) == [
        item.acquirer for item in ranked
    ]


def test_future_rows_cannot_change_selection_and_order_is_irrelevant(settings: Settings) -> None:
    module, policy = module_and_policy()
    experiment = import_module("evals.ranking.experiment")
    rows = [transaction(i, deal_year=year) for i, year in enumerate(range(2018, 2025), 1)]
    candidate = module.shared_candidate(settings.scoring).model_copy(update={"name": "same"})
    selection = experiment.select_candidates(rows, [candidate], settings.scoring, policy)
    changed = [row for row in rows if row.deal_year <= 2021]
    changed.append(transaction(99, deal_year=2022, acquirer="New", sector="Other"))
    assert selection == experiment.select_candidates(changed, [candidate], settings.scoring, policy)
    assert selection == experiment.select_candidates(
        rows[::-1], [candidate], settings.scoring, policy
    )
    assert selection.selected == "shared"
    assert selection.type_winner == "shared"
    assert [fold.train_end_year for fold in selection.folds] == [2018, 2019, 2020]
    assert [fold.test_rows for fold in selection.folds] == [1, 1, 1]


def test_benchmark_keeps_unseen_buyers_as_misses(settings: Settings) -> None:
    module, policy = module_and_policy()
    experiment = import_module("evals.ranking.experiment")
    policy = policy.model_copy(update={"bootstrap_samples": 20})
    rows = [transaction(i, deal_year=year) for i, year in enumerate(range(2018, 2022), 1)]
    rows += [transaction(7, deal_year=2022), transaction(8, deal_year=2024, acquirer="Unseen")]
    candidate = module.shared_candidate(settings.scoring).model_copy(update={"name": "same"})
    report = experiment.run_experiment(rows, [candidate], settings.scoring, policy)
    assert report.benchmark.test_rows == 2
    assert report.benchmark.unseen_labels == 1
    assert report.benchmark.metrics["shared"]["recall_at_k"] == 0.5
    assert report.selection.selected == "shared"
    assert set(report.lift) == {"shared", "global_popularity", "sector_popularity", "random"}
    assert all(value.mean == 0 for value in report.lift["shared"].values())
