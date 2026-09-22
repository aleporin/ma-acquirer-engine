"""Keep proposal inputs anonymous, reproducible, and confined to past history.

Owns: Aggregate arithmetic, packet completeness, and temporal privacy boundaries.
Does not own: Proposing or selecting ranking weights.
"""

import json
import math
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest

from acquirer_engine.data import Transaction
from acquirer_engine.errors import EvaluationError
from acquirer_engine.settings import Settings
from evals.ranking.weighting import ExperimentPolicy, load_policy
from tests.fixtures.ranking import transaction


def module_and_policy() -> tuple[ModuleType, ExperimentPolicy]:
    module = import_module("evals.ranking.packet")
    return module, load_policy(
        Path(__file__).resolve().parents[2] / "config/ranking_experiment.yaml"
    )


def history() -> list[Transaction]:
    return [
        transaction(1, deal_year=2017, deal_size_mm=100, ebitda_margin_pct=10),
        transaction(
            2,
            deal_year=2018,
            deal_size_mm=400,
            ebitda_margin_pct=30,
            sector="Other",
            outcome="Withdrawn",
            days_to_close=None,
        ),
        transaction(
            3, deal_year=2018, acquirer="Private Sponsor", acquirer_type="Financial Sponsor"
        ),
        transaction(
            4, deal_year=2018, acquirer="Pending Buyer", outcome="Pending", days_to_close=None
        ),
    ]


def test_packet_measures_all_eligible_buyers_and_correct_aggregate_formulas(
    settings: Settings,
) -> None:
    module, policy = module_and_policy()
    packet = module.build_packet(history(), policy, settings.scoring)
    assert packet["eligible_transactions"] == 4
    assert packet["eligible_buyers"] == 3
    population = packet["populations"]["Strategic"]
    assert population["buyer_count"] == 2
    assert population["transaction_summary"]["deal_count"] == 3
    buyers = population["buyers"]
    pair = next(buyer for buyer in buyers if buyer["deal_count"] == 2)
    assert pair["sector_hhi"] == 0.5
    assert [pair[key] for key in ("ev_mm_min", "ev_mm_median", "ev_mm_max")] == [100, 250, 400]
    assert pair["ev_ln_population_sd"] == pytest.approx(math.log(2), abs=1e-6)
    assert pair["margin_pct_median"] == 20
    assert pair["margin_population_cv"] == 0.5
    assert pair["completion_rate"] == 0.5
    assert pair["year_counts"] == {"2017": 1, "2018": 1}
    pending = next(buyer for buyer in buyers if buyer["completion_rate"] is None)
    assert pending["closed_count"] == pending["resolved_count"] == 0
    assert pending["ev_ln_population_sd"] == pending["margin_population_cv"] == 0
    assert "singleton" in " ".join(packet["limitations"]).lower()


def test_packet_does_not_disclose_identities_and_is_unchanged_by_renaming(
    settings: Settings,
) -> None:
    module, policy = module_and_policy()
    rows = history()
    packet = module.build_packet(rows, policy, settings.scoring)
    encoded = json.dumps(packet)
    for row in rows:
        for private in (row.acquirer, row.target_company, row.transaction_id):
            assert private not in encoded
    renamed = [
        row.model_copy(
            update={"acquirer": "Renamed " + row.acquirer, "target_company": "Confidential"}
        )
        for row in rows
    ]
    assert module.build_packet(renamed, policy, settings.scoring) == packet


def test_packet_and_digest_are_independent_of_row_order(settings: Settings) -> None:
    module, policy = module_and_policy()
    left = module.build_packet(history(), policy, settings.scoring)
    right = module.build_packet(history()[::-1], policy, settings.scoring)
    assert left == right
    assert module.packet_digest(left) == module.packet_digest(right)
    assert len(module.packet_digest(left)) == 64
    changed = dict(left, eligible_transactions=99)
    assert module.packet_digest(left) != module.packet_digest(changed)


def test_future_or_rumored_rows_cannot_change_the_packet(settings: Settings) -> None:
    module, policy = module_and_policy()
    baseline = module.build_packet(history(), policy, settings.scoring)
    excluded = [
        transaction(
            5, deal_year=policy.proposal_cutoff + 1, acquirer="Future Buyer", deal_size_mm=9e6
        ),
        transaction(6, deal_year=2024, acquirer="Benchmark Buyer", ebitda_margin_pct=99),
        transaction(7, deal_year=2017, outcome="Rumored", days_to_close=None),
    ]
    assert module.build_packet(history() + excluded, policy, settings.scoring) == baseline


def test_packet_includes_complete_population_and_frozen_proposal_bounds(settings: Settings) -> None:
    module, policy = module_and_policy()
    rows = [transaction(i, deal_year=2018, acquirer=f"Anonymous source {i}") for i in range(1, 61)]
    packet = module.build_packet(rows, policy, settings.scoring)
    assert len(packet["populations"]["Strategic"]["buyers"]) == packet["eligible_buyers"] == 60
    assert packet["base_weights"] == settings.scoring.weights
    assert packet["proposal_bounds"] == {
        "min_multiplier": policy.min_multiplier,
        "max_multiplier": policy.max_multiplier,
        "max_candidates": policy.max_candidates,
    }
    assert packet["proposal_cutoff"] == policy.proposal_cutoff
    with pytest.raises(EvaluationError, match="eligible"):
        module.build_packet([], policy, settings.scoring)
