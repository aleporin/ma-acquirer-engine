"""Run the ranked portfolio through bounded drafting and recovery.

Owns: Fan-out, generation outcomes, route decisions, and repair conversations.
Does not own: Resource construction, evidence queries, or portfolio review.
"""

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.usage import UsageLimits

from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, ValidationFailure
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.config import AnalystConfig
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.provider import output_errors
from acquirer_engine.llm.results import PageAttempt, PageResult
from acquirer_engine.llm.tools import PageDeps, PageSession, ToolState
from acquirer_engine.validation.schema import AcquirerRationale


async def run_analysts(packs: list[CorePack], deps: Deps) -> list[PageResult]:
    """Start other pages after the first response primes the shared prefix.

    Args:
        packs: Ranked buyer packs in output order.
        deps: Shared clients, cache, ledger, logger, and concurrency policy.
    Returns:
        Results in ranking order, including explicit failures.
    """
    if not packs:
        return []
    runtime = deps.runtime
    assert runtime is not None
    runtime.model.first_response.clear()
    semaphore = asyncio.Semaphore(deps.settings.analyst.concurrency)

    async def bounded(pack: CorePack) -> PageResult:
        async with semaphore:
            return await analyze_one(pack, deps)

    results: list[PageResult] = []
    index = 0
    while index < len(packs):
        current = asyncio.create_task(bounded(packs[index]))
        warm = asyncio.create_task(runtime.model.first_response.wait())
        try:
            await asyncio.wait((current, warm), return_when=asyncio.FIRST_COMPLETED)
            if runtime.model.first_response.is_set():
                return [
                    *results,
                    *await asyncio.gather(current, *(bounded(pack) for pack in packs[index + 1 :])),
                ]
            results.append(await current)
            index += 1
        finally:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
            if not current.done():
                current.cancel()
                await asyncio.gather(current, return_exceptions=True)
    return results


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
    config = deps.settings.analyst
    agent = (
        runtime.sparse_agent if pack.ranking.relevant_deals < config.sparse_relevant_deals else None
    )
    with runtime.model.scope(pack.ranking.acquirer) as scope:
        while True:
            outcome = await generate(agent or runtime.agent, deps, state, scope.stage, history)
            attempts.append(outcome.attempt)
            route = next_route(
                passed=outcome.attempt.status == "verified",
                repairable=outcome.repairable,
                repairs=state.generation,
                config=config,
            )
            runtime.trace.write("route_selected", pack.ranking.acquirer, route=route)
            if route in {"pass", "banner"}:
                break
            history = repair_history(outcome.messages, outcome.attempt.errors)
            if history is None:
                break
            state.generation += 1
            scope.stage = "escalation" if route == "escalate" else "repair"
            scope.role = "escalation" if route == "escalate" else "analyst"
            deps.logger.warning(
                "tier_escalated" if route == "escalate" else "repair_attempted",
                acquirer=pack.ranking.acquirer,
            )
    runtime.sessions[pack.ranking.acquirer] = PageSession(state, outcome.messages)
    return _page_result(pack, deps, state, outcome.output, attempts, started)


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
            banner="Unverified: " + "; ".join(attempts[-1].errors) if attempts[-1].errors else None,
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


@dataclass
class Generation:
    """One outcome and the unedited messages needed for targeted feedback."""

    output: AcquirerRationale | None
    attempt: PageAttempt
    messages: list[ModelMessage]
    repairable: bool


async def generate(
    agent: Agent[PageDeps, AcquirerRationale],
    deps: Deps,
    state: ToolState,
    stage: str,
    history: list[ModelMessage] | None,
) -> Generation:
    """Execute one generation, recording schema failures as well as parsed claims.
    Args:
        agent: Injected agent sharing the run's client and ledger.
        deps: Shared resources and validation settings.
        state: Evidence retained across generations for this page.
        stage: Label for this generation in measurements.
        history: Prior conversation ending with validation feedback, if any.
    Returns:
        Verified output or failure, with complete first-pass measurements.
    """
    state.claims_total = state.claims_verified = 0
    output, errors, repairable = None, [], False
    with capture_run_messages() as messages:
        try:
            result = await agent.run(
                None if history else data_block("core_evidence", state.core),
                message_history=history,
                deps=PageDeps(deps, state),
                usage_limits=UsageLimits(request_limit=deps.settings.analyst.max_tool_rounds + 1),
                infer_name=False,
            )
            output = result.output
        except ValidationFailure as error:
            errors, repairable = list(error.errors), True
        except UnexpectedModelBehavior as error:
            errors, repairable = output_errors(error), True
        except (AcquirerEngineError, ModelAPIError, UsageLimitExceeded, OSError) as error:
            errors = output_errors(error)
    attempt = PageAttempt(
        stage=stage,
        status="failed" if errors else "verified",
        errors=errors,
        claims_total=state.claims_total,
        claims_verified=state.claims_verified,
    )
    assert deps.runtime is not None
    deps.runtime.trace.write(
        "validation_completed", state.core.ranking.acquirer, attempt=attempt, rationale=output
    )
    deps.logger.info(
        "page_validated", stage=stage, acquirer=state.core.ranking.acquirer, passed=not errors
    )
    return Generation(output, attempt, messages, repairable)


type Route = Literal["pass", "repair", "escalate", "banner"]


def next_route(*, passed: bool, repairable: bool, repairs: int, config: AnalystConfig) -> Route:
    """Select the next action from a validation result and remaining attempts.

    Args:
        passed: Whether the complete page passed deterministic validation.
        repairable: Whether failure describes output the model can correct.
        repairs: Completed correction attempts, excluding the original draft.
        config: Loaded limits and escalation policy.
    Returns:
        One explicit action; every terminal failure remains unverified.
    """
    if passed:
        return "pass"
    if not repairable or repairs >= config.max_repairs:
        return "banner"
    if repairs == 0:
        return "repair"
    return "escalate" if repairs == 1 and config.escalation_enabled else "banner"


def repair_history(messages: list[ModelMessage], errors: list[str]) -> list[ModelMessage] | None:
    """Attach errors to the rejected output without discarding its evidence history.

    Args:
        messages: Captured conversation from the failed agent run.
        errors: Specific schema or evidence validation errors.
    Returns:
        A complete conversation, or None when no draft can be repaired.
    """
    if messages and isinstance(messages[-1], ModelRequest) and not messages[-1].parts:
        messages = messages[:-1]
    if not messages or not isinstance(messages[-1], ModelResponse):
        return None
    pending = [part for part in messages[-1].parts if isinstance(part, ToolCallPart)]
    if not pending:
        return None
    return [
        *messages,
        ModelRequest(
            parts=[
                RetryPromptPart(
                    content="\n".join(errors),
                    tool_name=part.tool_name,
                    tool_call_id=part.tool_call_id,
                )
                for part in pending
            ]
        ),
    ]
