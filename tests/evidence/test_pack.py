"""Specify evidence identity, scope, and context budgets.

Owns: Observable core-pack contracts on small synthetic histories.
Does not own: Provider token accounting or comparable-deal retrieval.
"""

import pytest
from acquirer_engine.evidence.ids import stat_id
from acquirer_engine.evidence.pack import build_core_pack

from acquirer_engine.errors import EvidenceError
from acquirer_engine.features.acquirer import AcquirerHistory, fit_features
from acquirer_engine.ranking.scorer import RankedAcquirer, rank_acquirers
from acquirer_engine.ranking.target import TargetProfile
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction


def test_stat_ids_preserve_scope_without_separator_collisions() -> None:
    assert stat_id("deal_count", "Buyer A") == "stat:deal_count:Buyer%20A"
    assert stat_id("a:b", "c") != stat_id("a", "b:c")
    assert stat_id("deal_count", "Buyer A") != stat_id("deal_count", "Buyer B")
    with pytest.raises(EvidenceError, match="nonempty"):
        stat_id("", "Buyer A")


def pack_inputs(settings: Settings) -> tuple[AcquirerHistory, RankedAcquirer, TargetProfile]:
    rows = [transaction(i) for i in range(1, 5)]
    rows.append(transaction(5, acquirer="Other Buyer"))
    fitted = fit_features(rows, settings.scoring, reference_year=2024)
    target = TargetProfile(
        sector="Services",
        deal_size_mm=200,
        ebitda_margin_pct=20,
        geography="Regional",
        ownership="Private",
        tags=(),
    )
    ranked = next(
        r for r in rank_acquirers(fitted, target, settings.scoring) if r.acquirer == "Buyer A"
    )
    return fitted.acquirers["Buyer A"], ranked, target


def test_core_pack_is_deterministic_thin_and_row_capped(settings: Settings) -> None:
    history, ranking, target = pack_inputs(settings)
    policy = settings.evidence.pack.model_copy(update={"max_rows": 2})
    pack = build_core_pack(history, ranking, target, policy)
    assert [r.transaction_id for r in pack.deals] == ["MA-2020-0001", "MA-2020-0002"]
    assert pack.total_rows == 4 and pack.truncated
    assert pack.ranking == ranking and pack.target == target
    assert all(row.acquirer == ranking.acquirer for row in pack.deals)
    assert pack == build_core_pack(history, ranking, target, policy)
    counts = [s for s in pack.statistics if s.metric == "deal_count"]
    assert len(counts) == 1 and counts[0].value == 4


def test_token_cap_covers_serialized_fixed_context_and_rows(settings: Settings) -> None:
    history, ranking, target = pack_inputs(settings)
    empty = build_core_pack(
        history, ranking, target, settings.evidence.pack.model_copy(update={"max_rows": 0})
    )
    budget = len(empty.model_dump_json().encode("utf-8"))
    policy = settings.evidence.pack.model_copy(update={"max_tokens": budget})
    pack = build_core_pack(history, ranking, target, policy)
    assert not pack.deals and pack.truncated
    assert pack.token_upper_bound <= budget
    with pytest.raises(EvidenceError, match="fixed context"):
        build_core_pack(history, ranking, target, policy.model_copy(update={"max_tokens": 1}))


def test_core_pack_rejects_mismatched_history(settings: Settings) -> None:
    history, ranking, target = pack_inputs(settings)
    with pytest.raises(EvidenceError, match="history"):
        build_core_pack(
            history,
            ranking.model_copy(update={"acquirer": "Other"}),
            target,
            settings.evidence.pack,
        )
