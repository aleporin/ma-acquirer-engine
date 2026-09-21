"""Exercise fit-only feature computation and learned adjacency.

Owns: Recency, completion, canonical comps, tags, and sector similarity.
Does not own: Weighted ranking or conviction.
"""

import pytest
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.features.tags import idf_weights
from acquirer_engine.ranking.target import TargetProfile, assignment_target

from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction


def test_common_tags_carry_less_weight() -> None:
    rows = [
        transaction(1, strategic_rationale_tags="Common|Rare"),
        transaction(2, strategic_rationale_tags="Common"),
    ]
    weights = idf_weights(rows)
    assert weights["Common"] == 0
    assert weights["Rare"] > weights["Common"]


def test_outcomes_recency_and_closed_stated_medians(settings: Settings) -> None:
    rows = [
        transaction(1, deal_year=2021, ev_ebitda_multiple=12),
        transaction(2, outcome="Withdrawn", days_to_close=None, ev_ebitda_multiple=90),
        transaction(3, outcome="Pending", days_to_close=None),
        transaction(4, outcome="Rumored", days_to_close=None),
        transaction(5, deal_year=2024),
    ]
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    buyer = fitted.acquirers["Buyer A"]
    assert buyer.deal_count == 3
    assert buyer.completion_rate == 0.5
    assert buyer.median_ev_ebitda == 12
    assert buyer.recency_count == pytest.approx(1 + 2 * 0.5 ** (1 / 3))
    assert len(fitted.training_ids) == 3


def test_sector_similarity_is_symmetric_discounted_and_learned(settings: Settings) -> None:
    rows = [
        transaction(1, acquirer="Sponsor", acquirer_type="Financial Sponsor", sector="A"),
        transaction(2, acquirer="Sponsor", acquirer_type="Financial Sponsor", sector="B"),
        transaction(
            3,
            acquirer="Other",
            sector="C",
            deal_size_mm=2000,
            ebitda_margin_pct=5,
            ev_ebitda_multiple=30,
        ),
    ]
    fitted = fit_features(rows, settings.scoring, reference_year=2021)
    assert fitted.similarity["A", "A"] == 1
    assert 0 < fitted.similarity["A", "B"] <= settings.scoring.adjacent_discount
    assert fitted.similarity["A", "B"] == fitted.similarity["B", "A"]
    assert fitted.similarity["A", "B"] > fitted.similarity["A", "C"]


def test_target_band_scales_and_margin_uses_only_supplied_rows(settings: Settings) -> None:
    target = TargetProfile(
        sector="Services",
        deal_size_mm=500,
        ebitda_margin_pct=20,
        geography="Regional",
        ownership="Private",
        tags=(),
    )
    assert target.size_band(settings.scoring) == (250, 1000)
    rows = [
        transaction(1, sector="Healthcare Services", ebitda_margin_pct=10),
        transaction(2, sector="Healthcare Services", ebitda_margin_pct=20),
        transaction(3, sector="Healthcare Services", ebitda_margin_pct=30),
    ]
    default = assignment_target(rows, settings.scoring)
    assert default.ebitda_margin_pct == pytest.approx(23.3333333333)
    assert default.deal_size_mm == 200


def test_input_order_cannot_change_fitted_features(settings: Settings) -> None:
    rows = [transaction(1), transaction(2, acquirer="Buyer B", sector="Other")]
    assert fit_features(rows, settings.scoring, reference_year=2021) == fit_features(
        rows[::-1], settings.scoring, reference_year=2021
    )
