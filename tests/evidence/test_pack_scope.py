"""Protect relevant history and completion denominators in capped evidence.

Owns: Regression cases for misleading omissions in thin buyer packs.
Does not own: Ranking policy or model prose quality.
"""

from acquirer_engine.evidence.pack import build_core_pack
from acquirer_engine.features.acquirer import fit_features
from acquirer_engine.ranking.scorer import rank_acquirers
from acquirer_engine.settings import Settings
from tests.evidence.test_pack import pack_inputs
from tests.fixtures.ranking import transaction


def test_pack_retains_older_exact_sector_before_recent_other_sector(settings: Settings) -> None:
    _, _, target = pack_inputs(settings)
    rows = [
        transaction(1, deal_year=2018),
        transaction(2, deal_year=2024, sector="Devices"),
        transaction(3, deal_year=2023, sector="Devices"),
    ]
    fitted = fit_features(rows, settings.scoring, reference_year=2024)
    ranking = rank_acquirers(fitted, target, settings.scoring)[0]
    policy = settings.evidence.pack.model_copy(update={"max_rows": 2})
    pack = build_core_pack(fitted.acquirers["Buyer A"], ranking, target, policy)
    assert [row.transaction_id for row in pack.deals] == ["MA-2018-0001", "MA-2024-0002"]
    assert pack.truncated and pack.total_rows == 3
    assert pack.token_upper_bound <= policy.max_tokens


def test_pack_counts_pending_separately_from_resolved_completion(settings: Settings) -> None:
    _, _, target = pack_inputs(settings)
    rows = [transaction(1), transaction(2, outcome="Pending", days_to_close=None)]
    fitted = fit_features(rows, settings.scoring, reference_year=2024)
    ranking = rank_acquirers(fitted, target, settings.scoring)[0]
    policy = settings.evidence.pack.model_copy(update={"max_rows": 0})
    pack = build_core_pack(fitted.acquirers["Buyer A"], ranking, target, policy)
    facts = {stat.metric: stat.value for stat in pack.statistics}
    assert facts["closed_count"] == 1
    assert facts["pending_count"] == 1
    assert facts["resolved_count"] == 1
    assert facts["completion_rate"] == 1
    assert not pack.deals
