"""Expose typed evidence queries to the analyst framework.

Owns: Tool signatures, per-page provenance, and trace/log emission.
Does not own: Query arithmetic or model-selected arguments.
"""

from pydantic_ai import RunContext, ToolReturn

from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.page_deps import PageDeps
from acquirer_engine.llm.tools import NumericBand, ToolResult


def _record(ctx: RunContext[PageDeps], result: ToolResult, arguments: object) -> ToolReturn:
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    ctx.deps.state.record(ctx.run_step, result)
    buyer = ctx.deps.state.core.ranking.acquirer
    runtime.trace.write(
        "tool_returned", buyer, round=ctx.run_step, arguments=arguments, result=result
    )
    ctx.deps.shared.logger.info(
        "tool_called",
        acquirer=buyer,
        stage="analyst",
        tool=result.tool,
        round=ctx.run_step,
        rows=len(result.rows),
        truncated=result.truncated,
    )
    return ToolReturn(return_value=data_block("tool_evidence", result))


async def get_comparable_deals(
    ctx: RunContext[PageDeps],
    sector: str,
    size_band: NumericBand,
    margin_band: NumericBand | None = None,
    geography: str | None = None,
) -> ToolReturn:
    """Retrieve Closed valuation comps; omit optional filters to widen sparse results.

    Args:
        ctx: Current page context.
        sector: Exact dataset sector.
        size_band: Enterprise value bounds in millions.
        margin_band: Optional EBITDA margin percentage bounds.
        geography: Optional exact region, or null for all regions.
    Returns:
        Bounded comparable rows and truncation metadata.
    """
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    result = runtime.tools.comparable_deals(sector, size_band, margin_band, geography)
    return _record(
        ctx,
        result,
        {
            "sector": sector,
            "size_band": size_band,
            "margin_band": margin_band,
            "geography": geography,
        },
    )


async def get_sector_stats(ctx: RunContext[PageDeps], sector: str) -> ToolReturn:
    """Retrieve full-population Closed-sector benchmarks with stable stat IDs.

    Args:
        ctx: Current page context.
        sector: Exact sector to benchmark.
    Returns:
        Closed counts and canonical medians, plus bounded supporting rows.
    """
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    return _record(ctx, runtime.tools.sector_stats(sector), {"sector": sector})


async def get_adjacent_sector_activity(
    ctx: RunContext[PageDeps],
    acquirer: str,
    sectors: tuple[str, ...],
) -> ToolReturn:
    """Retrieve buyer precedents in selected adjacent sectors.

    Args:
        ctx: Current page context.
        acquirer: Exact buyer identity.
        sectors: Sector labels relevant to the thesis.
    Returns:
        Bounded historical activity with evidence IDs.
    """
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    return _record(
        ctx,
        runtime.tools.adjacent_activity(acquirer, sectors),
        {"acquirer": acquirer, "sectors": sectors},
    )


async def get_sponsor_platform_history(
    ctx: RunContext[PageDeps], acquirer: str, sector: str
) -> ToolReturn:
    """Retrieve Closed sponsor platforms to distinguish a platform from an add-on.

    Args:
        ctx: Current page context.
        acquirer: Exact sponsor identity.
        sector: Requested platform sector.
    Returns:
        Bounded sponsor Platform Investment precedents.
    """
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    return _record(
        ctx,
        runtime.tools.platform_history(acquirer, sector),
        {"acquirer": acquirer, "sector": sector},
    )


async def get_failed_deals(ctx: RunContext[PageDeps], acquirer: str) -> ToolReturn:
    """Retrieve failed deals to support execution-risk flags.

    Args:
        ctx: Current page context.
        acquirer: Exact buyer identity.
    Returns:
        Bounded Withdrawn and Terminated deals.
    """
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
    return _record(ctx, runtime.tools.failed_deals(acquirer), {"acquirer": acquirer})
