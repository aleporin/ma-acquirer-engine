"""Specify bounded tool evidence and honest retrieval provenance.

Owns: Query filtering, canonical stats, and tool-round limits.
Does not own: Model choice or prompt interpretation.
"""

import pytest

from acquirer_engine.errors import BudgetExceeded
from acquirer_engine.llm.tools import EvidenceTools, NumericBand
from acquirer_engine.settings import Settings
from tests.fixtures.ranking import transaction
from tests.fixtures.rationale import evidence_context


def test_comps_filter_closed_rows_and_preserve_stated_multiples(settings: Settings) -> None:
    rows = (
        transaction(1, ev_ebitda_multiple=13.6),
        transaction(2, outcome="Pending", days_to_close=None),
        transaction(3, deal_size_mm=999),
        transaction(4, geography="West Coast"),
    )
    tools = EvidenceTools(rows, settings.analyst)
    result = tools.comparable_deals("Services", NumericBand(low=100, high=400), None, "Northeast")
    assert [r.transaction_id for r in result.rows] == ["MA-2020-0001"]
    assert result.rows[0].ev_ebitda_multiple == 13.6
    assert not result.truncated and result.total_rows == 1


def test_tool_caps_return_counts_without_silently_omitting_matches(settings: Settings) -> None:
    tools = EvidenceTools(
        tuple(transaction(i) for i in range(1, 6)),
        settings.analyst.model_copy(update={"tool_max_rows": 2}),
    )
    result = tools.comparable_deals("Services", NumericBand(low=100, high=400), None, None)
    assert len(result.rows) == 2 and result.truncated and result.total_rows == 5
    assert tools.comparable_deals("Unknown", NumericBand(low=1, high=2), None, None).total_rows == 0


def test_sector_stats_use_closed_rows_and_canonical_multiples(settings: Settings) -> None:
    tools = EvidenceTools(
        (
            transaction(1, ev_ebitda_multiple=10),
            transaction(2, ev_ebitda_multiple=20),
            transaction(3, outcome="Withdrawn", days_to_close=None, ev_ebitda_multiple=99),
        ),
        settings.analyst,
    )
    result = tools.sector_stats("Services")
    stats = {s.metric: s.value for s in result.statistics}
    assert stats["median_ev_ebitda_multiple"] == 15
    assert stats["closed_deal_count"] == 2
    assert all(row.outcome == "Closed" for row in result.rows)


def test_history_tools_apply_buyer_type_sector_and_outcome_filters(settings: Settings) -> None:
    rows = (
        transaction(1, acquirer_type="Financial Sponsor", deal_type="Platform Investment"),
        transaction(2, sector="Dental"),
        transaction(3, outcome="Terminated", days_to_close=None),
    )
    tools = EvidenceTools(rows, settings.analyst)
    assert len(tools.platform_history("Buyer A", "Services").rows) == 1
    assert [r.transaction_id for r in tools.adjacent_activity("Buyer A", ("Dental",)).rows] == [
        "MA-2020-0002"
    ]
    assert [r.transaction_id for r in tools.failed_deals("Buyer A").rows] == ["MA-2020-0003"]


def test_distinct_tool_rounds_are_bounded_and_noncomp_tools_cannot_supply_comps(
    settings: Settings,
) -> None:
    from acquirer_engine.llm.tool_state import ToolState

    context = evidence_context(settings)
    state = ToolState(context.core, settings.analyst.max_tool_rounds)
    tools = EvidenceTools(context.comparable_deals, settings.analyst)
    for step in range(settings.analyst.max_tool_rounds):
        state.record(step, tools.sector_stats("Services"))
        state.record(step, tools.sector_stats("Services"))
    assert not state.context().comparable_deals
    assert state.context().statistics
    with pytest.raises(BudgetExceeded, match="tool rounds"):
        state.record(settings.analyst.max_tool_rounds, tools.sector_stats("Services"))
