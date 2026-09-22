"""Request and archive bounded weight hypotheses through the recording boundary.

Owns: One typed proposal request, frozen inputs, and explicit replay provenance.
Does not own: Client construction, statistical selection, or production scoring.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, RootModel
from pydantic_ai import Agent, ModelRetry, ToolOutput
from pydantic_ai.usage import UsageLimits

from acquirer_engine.deps import RuntimeDeps
from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.cost import CallRecord
from acquirer_engine.llm.framing import data_block
from acquirer_engine.settings import Settings
from evals.ranking.weighting import Candidate, ExperimentPolicy, validate_proposals


class ProposalSet(BaseModel):
    """Hypotheses only; no metric or claim of measured improvement is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[Candidate]


class WeightVector(BaseModel):
    """Explicit fields survive the provider's strict JSON-schema transformation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    sector_fit: PositiveFloat
    size_fit: PositiveFloat
    recency: PositiveFloat
    completion: PositiveFloat
    profile_fit: PositiveFloat
    tag_fit: PositiveFloat
    geography_fit: PositiveFloat
    deal_type_fit: PositiveFloat


class TypeWeights(BaseModel):
    """Both buyer types are mandatory in the provider output grammar."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    sponsor: WeightVector = Field(alias="Financial Sponsor")
    strategic: WeightVector = Field(alias="Strategic")


class ProposedProfile(BaseModel):
    """Wire format converted into a validated local candidate after generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    explanation: str
    multipliers: TypeWeights


class ProposalResponse(BaseModel):
    """A closed provider schema with no unconstrained mapping fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[ProposedProfile]

    def hypotheses(self) -> ProposalSet:
        """Convert explicit wire fields into the internal bounded candidate contract."""
        return ProposalSet.model_validate(self.model_dump(by_alias=True))


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
    agent: Agent[None, ProposalResponse] = Agent(
        recorded,
        output_type=ToolOutput(ProposalResponse, strict=True),
        instructions=prompt,
        retries=0,
        model_settings={"max_tokens": policy.max_output_tokens},
    )

    @agent.output_validator
    def validate(output: ProposalResponse) -> ProposalResponse:
        try:
            validate_proposals(output.hypotheses().candidates, policy, deps.settings.scoring)
        except EvaluationError as error:
            raise ModelRetry(str(error)) from error
        return output

    with recorded.scope("weight-proposals") as scope:
        scope.stage = "ranking_proposal"
        result = await agent.run(
            data_block("history", RootModel[dict[str, Any]](packet)),
            usage_limits=UsageLimits(request_limit=1),
        )
    return result.output.hypotheses()
