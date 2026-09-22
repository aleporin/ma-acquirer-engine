"""Summarize supplied comparison facts through the existing recording boundary.

Owns: A single optional, bounded model response and its versioned prompt.
Does not own: Client construction or accepting the prose as verified evidence.
"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationInfo, model_validator
from pydantic_ai import Agent, ToolOutput
from pydantic_ai.usage import UsageLimits

from acquirer_engine.comparison.ranking import ComparisonData
from acquirer_engine.deps import Deps
from acquirer_engine.llm.framing import data_block


class ComparisonPolicy(BaseModel):
    """Configuration for the optional comparison interpretation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    prompt_file: str
    max_output_tokens: PositiveInt
    summary_chars: PositiveInt


class ComparisonSummary(BaseModel):
    """A bounded interpretation, displayed separately from computed facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    summary: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def configured_length(self, info: ValidationInfo) -> Self:
        """Enforce the same configured size limit in test and live execution."""
        if not isinstance(info.context, ComparisonPolicy):
            raise ValueError("Comparison policy is required")
        if len(self.summary) > info.context.summary_chars:
            raise ValueError("Comparison summary exceeds configured length")
        return self


async def summarize(
    data: ComparisonData,
    deps: Deps,
    prompt: str,
    policy: ComparisonPolicy,
) -> ComparisonSummary:
    """Request one interpretation with no tools, output retries, or extra requests.

    Args:
        data: Computed comparison facts, delimited as untrusted data.
        deps: Prebuilt client, ledger, cache, trace, and logger via runtime.
        prompt, policy: Versioned instructions and configured output bound.
    Returns:
        Unverified prose interpretation; the computed table remains authoritative.
    """
    assert deps.runtime is not None
    recorded = deps.runtime.model
    agent: Agent[None, ComparisonSummary] = Agent(
        recorded,
        output_type=ToolOutput(ComparisonSummary, strict=True),
        instructions=prompt,
        validation_context=policy,
        retries=0,
        model_settings={"max_tokens": policy.max_output_tokens},
    )
    with recorded.scope("target-comparison") as scope:
        scope.stage = "comparison"
        result = await agent.run(
            data_block("comparison_data", data), usage_limits=UsageLimits(request_limit=1)
        )
    return result.output
