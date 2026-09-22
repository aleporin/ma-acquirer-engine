"""Review the portfolio once and revalidate one revision for each flagged page.

Owns: Structured critique, bounded revisions, and preserved original pages.
Does not own: Ranking, provider construction, or automatic approval of edits.
"""

import asyncio
from time import perf_counter

from pydantic import BaseModel
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.usage import UsageLimits

from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError
from acquirer_engine.llm.analyst import generate, repair_history
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.provider import output_errors
from acquirer_engine.llm.results import PageResult, ReviewResult, ReviewVerdict
from acquirer_engine.validation.schema import AcquirerRationale


class ReviewPage(BaseModel):
    """Stable reviewer input excludes execution times and volatile run identities."""

    acquirer: str
    rationale: AcquirerRationale | None
    errors: list[str]


class PortfolioInput(BaseModel):
    """The complete portfolio in its ranked order."""

    pages: list[ReviewPage]


async def review_portfolio(
    pages: list[PageResult], deps: Deps
) -> tuple[list[PageResult], ReviewResult | None]:
    """Apply one portfolio verdict and at most one revision per flagged buyer.
    Args:
        pages: Original analyst outcomes, retained unchanged by the caller.
        deps: Shared runtime and configuration.
    Returns:
        Revalidated pages and reviewer diagnostics, or disabled-review passthrough.
    """
    runtime = deps.runtime
    assert runtime is not None
    if not deps.settings.analyst.reviewer_enabled or runtime.reviewer is None or not pages:
        return pages, None
    portfolio = PortfolioInput.model_validate(
        {
            "pages": [
                dict(acquirer=p.acquirer, rationale=p.rationale, errors=p.errors) for p in pages
            ]
        },
        context=deps.settings.evidence.validation,
    )
    try:
        with runtime.model.scope("portfolio") as scope:
            scope.stage = "reviewer"
            result = await runtime.reviewer.run(
                data_block("portfolio", portfolio),
                deps=tuple(p.acquirer for p in pages),
                usage_limits=UsageLimits(request_limit=1),
                infer_name=False,
            )
    except (
        AcquirerEngineError,
        ModelAPIError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
        OSError,
    ) as error:
        return pages, ReviewResult(errors=output_errors(error))
    verdicts = {v.acquirer: v for v in result.output.verdicts}
    semaphore = asyncio.Semaphore(deps.settings.analyst.concurrency)

    async def revise(page: PageResult) -> PageResult:
        if verdicts[page.acquirer].decision == "approve":
            return page
        async with semaphore:
            return await _revise(page, verdicts[page.acquirer], deps)

    final = list(await asyncio.gather(*(revise(page) for page in pages)))
    return final, ReviewResult(verdicts=result.output.verdicts)


async def _revise(page: PageResult, verdict: ReviewVerdict, deps: Deps) -> PageResult:
    runtime = deps.runtime
    assert runtime is not None
    session = runtime.sessions[page.acquirer]
    history = session.messages
    if page.status == "failed":
        history = repair_history(history, page.errors) or history
    history = [
        *history,
        ModelRequest(parts=[UserPromptPart(data_block("portfolio_feedback", verdict))]),
    ]
    state = session.state
    state.generation += 1
    started = perf_counter()
    agent = (
        runtime.sparse_agent
        if state.core.ranking.relevant_deals < deps.settings.analyst.sparse_relevant_deals
        else None
    )
    with runtime.model.scope(page.acquirer, resume=True) as scope:
        scope.stage = "revision"
        outcome = await generate(agent or runtime.agent, deps, state, "revision", history)
    return page.model_copy(
        update={
            "status": outcome.attempt.status,
            "rationale": outcome.output,
            "errors": outcome.attempt.errors,
            "banner": "Unverified: " + "; ".join(outcome.attempt.errors)
            if outcome.attempt.errors
            else None,
            "attempts": [*page.attempts, outcome.attempt],
            "claims_total": state.claims_total,
            "claims_verified": state.claims_verified,
            "latency_seconds": page.latency_seconds + perf_counter() - started,
            "tools": [r.tool for r in state.results],
        }
    )
