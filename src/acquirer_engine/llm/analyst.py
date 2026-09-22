"""Generate, validate, and route one buyer page to its final outcome.

Owns: The bounded draft, repair, and escalation loop and failure isolation.
Does not own: Resource construction, batch scheduling, or portfolio review.
"""

from time import perf_counter

from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.attempts import generate
from acquirer_engine.llm.context import PageSession, ToolState
from acquirer_engine.llm.results import PageAttempt, PageResult
from acquirer_engine.llm.router import next_route
from acquirer_engine.validation.repair import repair_history
from acquirer_engine.validation.schema import AcquirerRationale


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
