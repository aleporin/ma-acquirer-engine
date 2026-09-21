"""Compose and run a typed analyst using injected execution resources.

Owns: Agent construction, output validation, and per-page failure isolation.
Does not own: Ranking, portfolio review, escalation, or client construction.
"""

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pydantic_ai import Agent, RunContext, ToolOutput
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModelSettings

from acquirer_engine.data.schema import Transaction
from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm import bindings
from acquirer_engine.llm.attempts import generate
from acquirer_engine.llm.cache import ResponseCache
from acquirer_engine.llm.cost import CostLedger, ExecutionMode
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.page_deps import PageDeps
from acquirer_engine.llm.recording import RecordedModel
from acquirer_engine.llm.results import PageAttempt, PageResult
from acquirer_engine.llm.tool_state import ToolState
from acquirer_engine.llm.tools import EvidenceTools
from acquirer_engine.llm.trace import TraceWriter
from acquirer_engine.llm.trace_replay import ResponseArchive
from acquirer_engine.validation.claims import validate_rationale, verified_claim_count
from acquirer_engine.validation.repair import repair_history
from acquirer_engine.validation.schema import AcquirerRationale


@dataclass(frozen=True)
class AnalystServices:
    """Run-wide resources constructed once before any page tasks start."""

    agent: Agent[PageDeps, AcquirerRationale]
    model: RecordedModel
    tools: EvidenceTools
    trace: TraceWriter


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


def build_services(
    deps: Deps,
    model: Model | None,
    rows: tuple[Transaction, ...],
    root: Path,
    prompt: str,
    *,
    mode: ExecutionMode,
    cache_root: Path | None = None,
    archive: ResponseArchive | None = None,
) -> AnalystServices:
    """Compose an analyst once from its dependencies, never inside a request.

    Args:
        deps: Shared configuration and logger.
        model: One provider model, test model, or no model for replay.
        rows: Eligible run history used by evidence queries.
        root: Local run artifact directory.
        prompt: Versioned instructions read at the command boundary.
        mode: Live, test, or strictly cache-only replay.
        cache_root: Shared response cache location.
        archive: Original run's responses for historical replay.
    Returns:
        One agent, recording boundary, query service, and trace sink.
    """
    config = deps.settings.analyst
    trace = TraceWriter(root / "trace.jsonl")
    recorded = RecordedModel(
        model,
        deps,
        ResponseCache(cache_root or root / "cache"),
        CostLedger(deps.settings.models.roles["analyst"]),
        trace,
        mode=mode,
        archive=archive,
    )
    agent = _build_agent(recorded, deps, prompt)
    return AnalystServices(agent, recorded, EvidenceTools(rows, config), trace)


async def analyze_one(pack: CorePack, deps: Deps) -> PageResult:
    """Run one page to verified output or an explicit error outcome.

    Args:
        pack: Thin evidence for this buyer.
        deps: Shared agent resources and policy.
    Returns:
        A verified rationale or failed-page errors, preserving other page tasks.
    """
    runtime = deps.runtime
    assert runtime is not None
    state = ToolState(pack, deps.settings.analyst.max_tool_rounds)
    started = perf_counter()
    attempts: list[PageAttempt] = []
    history = None
    with runtime.model.scope(pack.ranking.acquirer) as scope:
        while True:
            outcome = await generate(runtime.agent, deps, state, scope.stage, history)
            attempts.append(outcome.attempt)
            if not outcome.repairable or state.generation >= deps.settings.analyst.max_repairs:
                break
            history = repair_history(outcome.messages, outcome.attempt.errors)
            if history is None:
                break
            state.generation += 1
            scope.stage = "repair"
            deps.logger.warning("repair_attempted", acquirer=pack.ranking.acquirer)
    return _page_result(pack, deps, state, outcome.output, attempts, started)


def _build_agent(
    recorded: RecordedModel, deps: Deps, prompt: str
) -> Agent[PageDeps, AcquirerRationale]:
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
        tools=[
            bindings.get_comparable_deals,
            bindings.get_sector_stats,
            bindings.get_adjacent_sector_activity,
            bindings.get_sponsor_platform_history,
            bindings.get_failed_deals,
        ],
    )
    agent.output_validator(_validate)
    return agent


def _page_result(
    pack: CorePack,
    deps: Deps,
    state: ToolState,
    output: AcquirerRationale | None,
    attempts: list[PageAttempt],
    started: float,
) -> PageResult:
    return PageResult.model_validate(
        dict(
            acquirer=pack.ranking.acquirer,
            acquirer_type=pack.ranking.acquirer_type,
            status=attempts[-1].status,
            rationale=output,
            errors=attempts[-1].errors,
            attempts=attempts,
            tools=[r.tool for r in state.results],
            latency_seconds=perf_counter() - started,
            claims_total=state.claims_total,
            claims_verified=state.claims_verified,
        ),
        context=deps.settings.evidence.validation,
    )
