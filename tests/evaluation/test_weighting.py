"""Specify bounded experimental weights independently of the shipped ranker.

Owns: Proposal validation, normalization, type differences, and sparse shrinkage.
Does not own: Choosing weights from benchmark outcomes.
"""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from acquirer_engine.errors import EvaluationError
from acquirer_engine.ranking.features import fit_features
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction


def module_and_policy() -> tuple[ModuleType, Any]:
    module = import_module("evals.ranking.weighting")
    root = Path(__file__).resolve().parents[2]
    return module, module.load_policy(root / "config/ranking_experiment.yaml")


def test_proposals_require_both_types_and_all_features_with_bounded_values(
    settings: Settings,
) -> None:
    module, policy = module_and_policy()
    candidate = module.shared_candidate(settings.scoring)
    module.validate_candidates([candidate], policy, settings.scoring)
    for mutation in ("missing_type", "missing_feature", "out_of_bounds", "duplicate"):
        raw = candidate.model_dump()
        if mutation == "missing_type":
            del raw["multipliers"]["Strategic"]
        elif mutation == "missing_feature":
            del raw["multipliers"]["Strategic"]["sector_fit"]
        elif mutation == "out_of_bounds":
            raw["multipliers"]["Strategic"]["sector_fit"] = policy.max_multiplier + 1
        candidates = [module.Candidate.model_validate(raw)]
        if mutation == "duplicate":
            candidates *= 2
        with pytest.raises(EvaluationError):
            module.validate_candidates(candidates, policy, settings.scoring)


def test_type_weights_are_normalized_and_do_not_modify_the_default(settings: Settings) -> None:
    module, policy = module_and_policy()
    original = settings.scoring.model_dump_json()
    candidate = module.shared_candidate(settings.scoring)
    candidate.multipliers["Financial Sponsor"]["size_fit"] = 2
    rows = [transaction(acquirer_type="Financial Sponsor")]
    buyer = fit_features(rows, settings.scoring, reference_year=2021).acquirers["Buyer A"]
    weights = module.buyer_weights(candidate, buyer, settings.scoring, policy, strength=0)
    assert sum(weights.values()) == pytest.approx(1)
    assert weights["size_fit"] > settings.scoring.weights["size_fit"]
    assert settings.scoring.model_dump_json() == original


def test_sparse_buyer_adjustments_stay_closer_to_the_type_default(settings: Settings) -> None:
    module, policy = module_and_policy()
    candidate = module.shared_candidate(settings.scoring)
    rows = [transaction(i, acquirer="Frequent") for i in range(1, 21)]
    rows.append(transaction(21, acquirer="Sparse"))
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    weights = {
        name: module.buyer_weights(
            candidate, buyer, settings.scoring, policy, strength=policy.buyer_strength
        )
        for name, buyer in fitted.acquirers.items()
    }
    assert settings.scoring.weights["sector_fit"] < weights["Sparse"]["sector_fit"]
    assert weights["Sparse"]["sector_fit"] < weights["Frequent"]["sector_fit"]
    assert all(sum(weight.values()) == pytest.approx(1) for weight in weights.values())
