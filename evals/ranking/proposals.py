"""Request and archive bounded weight hypotheses through the recording boundary.

Owns: One typed proposal request, frozen inputs, and explicit replay provenance.
Does not own: Client construction, statistical selection, or production scoring.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel
from pydantic_ai import Agent, ModelRetry, ToolOutput
from pydantic_ai.usage import UsageLimits

from acquirer_engine.deps import RuntimeDeps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.cost import CallRecord
from acquirer_engine.llm.framing import data_block
from acquirer_engine.settings import Settings
from evals.ranking.weighting import Candidate, ExperimentPolicy, validate_candidates


class ProposalSet(BaseModel):
    """Hypotheses only; no metric or claim of measured improvement is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[Candidate]


class ProposalSnapshot(BaseModel):
    """The complete non-secret request inputs needed for exact offline replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    settings: Settings
    policy: ExperimentPolicy
    packet: dict[str, Any]
    packet_sha256: str
    prompt: str
    git_sha: str
    source_dirty: bool


class ProposalRun(BaseModel):
    """Outcome, original source identity, and real request accounting."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    replay_of: str | None = None
    git_sha: str
    source_dirty: bool
    packet_sha256: str
    snapshot_sha256: str
    candidates: list[Candidate] = []
    calls: tuple[CallRecord, ...] = ()
    errors: tuple[str, ...] = ()
    uncertain_cost_bound_usd: float = 0


def proposal_settings(settings: Settings, policy: ExperimentPolicy) -> Settings:
    """Apply the frozen single-request budget without changing product settings."""
    analyst = settings.analyst.model_copy(
        update={
            "max_output_tokens": policy.max_output_tokens,
            "max_run_usd": policy.max_run_usd,
            "request_timeout_seconds": policy.request_timeout_seconds,
            "run_timeout_seconds": policy.run_timeout_seconds,
            "sdk_retries": policy.max_retries,
            "output_retries": 0,
            "max_repairs": 0,
            "escalation_enabled": False,
            "reviewer_enabled": False,
            "tools_enabled": False,
        }
    )
    return settings.model_copy(update={"analyst": analyst})


async def request_proposals(
    packet: dict[str, Any],
    deps: RuntimeDeps,
    prompt: str,
    policy: ExperimentPolicy,
) -> ProposalSet:
    """Make exactly one recorded request, rejecting invalid hypotheses without retry."""
    recorded = deps.runtime.model
    agent: Agent[None, ProposalSet] = Agent(
        recorded,
        output_type=ToolOutput(ProposalSet, strict=True),
        instructions=prompt,
        retries=0,
        model_settings={"max_tokens": policy.max_output_tokens},
    )

    @agent.output_validator
    def validate(output: ProposalSet) -> ProposalSet:
        try:
            validate_candidates(output.candidates, policy, deps.settings.scoring)
            if any(candidate.name == "shared" for candidate in output.candidates):
                raise EvaluationError("The name shared is reserved for the unchanged control")
        except EvaluationError as error:
            raise ModelRetry(str(error)) from error
        return output

    with recorded.scope("weight-proposals") as scope:
        scope.stage = "ranking_proposal"
        result = await agent.run(
            data_block("history", RootModel[dict[str, Any]](packet)),
            usage_limits=UsageLimits(request_limit=1),
        )
    return result.output
