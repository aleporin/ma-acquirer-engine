"""Specify complete type policies, historical compatibility, and score arithmetic.

Owns: Buyer-type weight selection and ablation behavior.
Does not own: Choosing a policy from predictive measurements.
"""

import pytest
from pydantic import ValidationError

from acquirer_engine.ranking.config import RankingConfig
from acquirer_engine.ranking.features import fit_features
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction
from tests.ranking.test_scorer import target


def type_policy(settings: Settings) -> RankingConfig:
    payload = settings.scoring.model_dump()
    sponsor = dict.fromkeys(settings.scoring.weights, 0.0)
    sponsor.update({"size_fit": 0.75, "sector_fit": 0.25})
    strategic = dict.fromkeys(settings.scoring.weights, 0.0)
    strategic.update({"size_fit": 0.25, "sector_fit": 0.75})
    payload["type_weights"] = {"Financial Sponsor": sponsor, "Strategic": strategic}
    return RankingConfig.model_validate(payload)


@pytest.mark.parametrize("drop", [None, "sector_fit"])
def test_each_type_uses_its_own_weights_including_ablation(
    settings: Settings, drop: str | None
) -> None:
    policy = type_policy(settings)
    rows = [
        transaction(1, acquirer="Sponsor", acquirer_type="Financial Sponsor", sector="Other"),
        transaction(2, acquirer="Strategic", acquirer_type="Strategic", sector="Other"),
    ]
    fitted = fit_features(rows, policy, reference_year=2021)
    ranked = rank_acquirers(fitted, target(), policy, drop="sector_fit" if drop else None)
    assert ranked[0].acquirer == "Sponsor"
    for buyer in ranked:
        expected = policy.model_dump()["type_weights"][buyer.acquirer_type]
        denominator = 1 - expected["sector_fit"] if drop else 1
        assert buyer.signals["size_fit"].weight == pytest.approx(expected["size_fit"] / denominator)
        assert sum(s.weight for s in buyer.signals.values()) == pytest.approx(1)
        assert buyer.score == pytest.approx(sum(s.contribution for s in buyer.signals.values()))


def test_historical_policy_without_type_weights_keeps_shared_scores(settings: Settings) -> None:
    payload = settings.scoring.model_dump(exclude={"type_weights"})
    legacy = RankingConfig.model_validate(payload)
    assert legacy.model_dump()["type_weights"] == {}
    ranked = rank_acquirers(
        fit_features([transaction()], legacy, reference_year=2021), target(), legacy
    )
    assert {name: signal.weight for name, signal in ranked[0].signals.items()} == pytest.approx(
        legacy.weights
    )


@pytest.mark.parametrize("defect", ["missing_type", "missing_feature", "wrong_sum"])
def test_partial_or_unnormalized_type_policies_are_rejected(
    settings: Settings, defect: str
) -> None:
    payload = type_policy(settings).model_dump()
    if defect == "missing_type":
        del payload["type_weights"]["Strategic"]
    elif defect == "missing_feature":
        del payload["type_weights"]["Strategic"]["recency"]
    else:
        payload["type_weights"]["Strategic"]["size_fit"] = 0.5
    with pytest.raises(ValidationError, match="type weights"):
        RankingConfig.model_validate(payload)
