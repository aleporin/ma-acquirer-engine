"""Run and measure one analyst generation independently of routing policy.

Owns: Captured conversations, typed failure isolation, and attempt-level validation.
Does not own: Deciding whether to repair, escalate, or publish a page.
"""

from dataclasses import dataclass

from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import UsageLimits

from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, ValidationFailure
from acquirer_engine.llm.framing import data_block
from acquirer_engine.llm.output import output_errors
from acquirer_engine.llm.page_deps import PageDeps
from acquirer_engine.llm.results import PageAttempt
from acquirer_engine.llm.tool_state import ToolState
from acquirer_engine.validation.schema import AcquirerRationale


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
