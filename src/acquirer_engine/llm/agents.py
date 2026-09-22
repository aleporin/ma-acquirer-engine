"""Bind typed agents to evidence tools and output validators.

Owns: Agent construction, tool signatures, retrieval provenance, and validation
Does not own: Query arithmetic, shared resource lifetime, or page routing.
"""

from pydantic_ai import Agent, RunContext, ToolOutput, ToolReturn
from pydantic_ai.models.anthropic import AnthropicModelSettings

from acquirer_engine.deps import Deps
from acquirer_engine.errors import ValidationFailure
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.recording import RecordedModel
from acquirer_engine.llm.results import PortfolioVerdicts
from acquirer_engine.llm.tools import NumericBand, PageDeps, ToolResult
from acquirer_engine.validation.claims import validate_rationale, verified_claim_count
from acquirer_engine.validation.schema import AcquirerRationale


def _validate(ctx: RunContext[PageDeps], output: AcquirerRationale) -> AcquirerRationale:
    state = ctx.deps.state
    config = ctx.deps.shared.settings.evidence.validation
    state.claims_total = len(output.claims)
    state.claims_verified = verified_claim_count(output, state.context(), config)
    runtime = ctx.deps.shared.runtime
    runtime.trace.write("draft_received", state.core.ranking.acquirer, rationale=output)
    return validate_rationale(
        output.model_dump(), ctx.deps.state.context(), ctx.deps.shared.settings.evidence.validation
    )


def build_analyst(
    recorded: RecordedModel, deps: Deps, prompt: str
) -> Agent[PageDeps, AcquirerRationale]:
    """Bind the injected model to the page contract and evidence tools.

    Args:
        recorded: Shared request, usage, and replay boundary.
        deps: Loaded run policy.
        prompt: Frozen primary or sparse instructions.
    Returns:
        Agent with deterministic output validation and bounded tools.
    """
    config = deps.settings.analyst
    model_settings = AnthropicModelSettings(
        max_tokens=config.max_output_tokens,
        anthropic_cache_instructions=True,
        anthropic_cache_tool_definitions=True,
    )
    if config.temperature is not None:
        model_settings["temperature"] = config.temperature
    agent = Agent(
        recorded,
        output_type=ToolOutput(AcquirerRationale, strict=True),
        deps_type=PageDeps,
        instructions=lambda ctx: (
            prompt
            + "\n"
            + data_block("target_profile", ctx.deps.state.core.target)
            + "\n"
            + data_block("execution_policy", config, exclude_unset=True)
            + "\n"
            + data_block("validation_policy", deps.settings.evidence.validation)
        ),
        validation_context=deps.settings.evidence.validation,
        model_settings=model_settings,
        retries={"output": config.output_retries, "tools": config.output_retries},
        tools=[]
        if not config.tools_enabled
        else [
            get_comparable_deals,
            get_sector_stats,
            get_adjacent_sector_activity,
            get_sponsor_platform_history,
            get_failed_deals,
        ],
    )
    agent.output_validator(_validate)
    return agent


def _coverage(ctx: RunContext[tuple[str, ...]], output: PortfolioVerdicts) -> PortfolioVerdicts:
    names = [v.acquirer for v in output.verdicts]
    if len(names) != len(set(names)) or set(names) != set(ctx.deps):
        raise ValidationFailure(["Review must name every supplied acquirer exactly once"])
    return output


def build_reviewer(
    recorded: RecordedModel, prompt: str, tokens: int
) -> Agent[tuple[str, ...], PortfolioVerdicts]:
    """Construct the reviewer with the run's existing recording boundary.

    Args:
        recorded: Shared client, ledger, cache, trace, and spending guard.
        prompt: Versioned prompt text frozen in the input snapshot.
        tokens: Configured output cap for this smaller response contract.
    Returns:
        A tool-free reviewer with strict buyer coverage validation.
    """
    agent = Agent(
        recorded,
        deps_type=tuple[str, ...],
        output_type=ToolOutput(PortfolioVerdicts, strict=True),
        instructions=prompt,
        model_settings={"max_tokens": tokens},
        retries=0,
    )
    agent.output_validator(_coverage)
    return agent


def _record(ctx: RunContext[PageDeps], result: ToolResult, arguments: object) -> ToolReturn:
    runtime = ctx.deps.shared.runtime
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
    return _record(ctx, runtime.tools.failed_deals(acquirer), {"acquirer": acquirer})
