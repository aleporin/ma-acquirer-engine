"""Declare typed agents and register their output validators.

Owns: Agent instructions, tool registration, and validation bindings.
Does not own: Resource construction, scheduling, or page routing.
"""

from pydantic_ai import Agent, RunContext, ToolOutput
from pydantic_ai.models.anthropic import AnthropicModelSettings

from acquirer_engine.deps import Deps
from acquirer_engine.errors import ValidationFailure
from acquirer_engine.llm import bindings
from acquirer_engine.llm.context import PageDeps
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.recording import RecordedModel
from acquirer_engine.llm.review_schema import PortfolioVerdicts
from acquirer_engine.validation.claims import validate_rationale, verified_claim_count
from acquirer_engine.validation.schema import AcquirerRationale


def _validate(ctx: RunContext[PageDeps], output: AcquirerRationale) -> AcquirerRationale:
    state = ctx.deps.state
    config = ctx.deps.shared.settings.evidence.validation
    state.claims_total = len(output.claims)
    state.claims_verified = verified_claim_count(output, state.context(), config)
    runtime = ctx.deps.shared.runtime
    assert runtime is not None
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
            bindings.get_comparable_deals,
            bindings.get_sector_stats,
            bindings.get_adjacent_sector_activity,
            bindings.get_sponsor_platform_history,
            bindings.get_failed_deals,
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
