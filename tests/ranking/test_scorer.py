"""Check observable ranking behavior on synthetic transactions.

Owns: Score decomposition, tie-breaking, outcome policy, and conviction.
Does not own: Claims about predictive quality.
"""

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as property_settings
from hypothesis import strategies as st

from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.ranking.conviction import conviction
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.ranking.target import TargetProfile
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction


def target() -> TargetProfile:
    """Build a query whose financial and geographic assumptions are explicit."""
    return TargetProfile(
        sector="Services",
        deal_size_mm=200,
        ebitda_margin_pct=20,
        geography="Regional",
        ownership="Private",
        tags=("Scale",),
    )


def test_breakdown_sums_to_score_and_ties_sort_by_name(settings: Settings) -> None:
    rows = [transaction(1, acquirer="Zed"), transaction(2, acquirer="Alpha")]
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    ranked = rank_acquirers(fitted, target(), settings.scoring)
    assert [item.acquirer for item in ranked] == ["Alpha", "Zed"]
    for item in ranked:
        assert item.score == pytest.approx(
            sum(signal.contribution for signal in item.signals.values())
        )
        assert set(item.signals) == set(settings.scoring.weights)
        assert 0 <= item.score <= 1


def test_direct_sector_beats_distant_economics_without_a_type_quota(settings: Settings) -> None:
    rows = [
        transaction(1, acquirer="Direct"),
        transaction(
            2, acquirer="Distant", sector="Devices", deal_size_mm=5000, ebitda_margin_pct=5
        ),
    ]
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    ranked = rank_acquirers(fitted, target(), settings.scoring)
    assert ranked[0].acquirer == "Direct"
    assert all(item.acquirer_type == "Strategic" for item in ranked)


def test_ablation_removes_one_group_and_renormalizes(settings: Settings) -> None:
    fitted = fit_features([transaction()], settings.scoring, reference_year=2021)
    ranked = rank_acquirers(fitted, target(), settings.scoring, drop="sector_fit")
    assert ranked[0].signals["sector_fit"].weight == 0
    assert sum(signal.weight for signal in ranked[0].signals.values()) == pytest.approx(1)


def test_conviction_uses_fixed_signals_without_forcing_levels(settings: Settings) -> None:
    config = settings.scoring
    assert conviction(0.9, 4, config) == "High"
    assert conviction(0.9, 1, config) == "Medium"
    assert conviction(0.55, 3, config) == "Medium"
    assert conviction(0.3, 10, config) == "Low"
    assert {conviction(0.9, 4, config) for _ in range(10)} == {"High"}


@property_settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=30)
@given(st.floats(min_value=1, max_value=10000))
def test_rank_scores_are_bounded_and_independent_of_row_order(
    settings: Settings, size: float
) -> None:
    rows = [
        transaction(1, deal_size_mm=size),
        transaction(2, acquirer="Buyer B"),
        transaction(3, acquirer="Buyer B", outcome="Terminated", days_to_close=None),
    ]
    left = rank_acquirers(
        fit_features(rows, settings.scoring, reference_year=2021), target(), settings.scoring
    )
    right = rank_acquirers(
        fit_features(rows[::-1], settings.scoring, reference_year=2021), target(), settings.scoring
    )
    assert left == right
    assert all(0 <= item.score <= 1 for item in left)
