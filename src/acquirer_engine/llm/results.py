"""Define analyst and reviewer outcomes retained in each run.

Owns: Typed attempts, pages, review verdicts, and serialized run artifacts.
Does not own: Routing, rendering, or judging narrative quality.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from acquirer_engine.data.schema import AcquirerType
from acquirer_engine.llm.cost import CallRecord, ExecutionMode
from acquirer_engine.validation.schema import AcquirerRationale


class ReviewVerdict(BaseModel):
    """One decision with actionable feedback when a revision is requested."""

    model_config = ConfigDict(extra="forbid")
    acquirer: str
    decision: Literal["approve", "revise"]
    critique: str

    @model_validator(mode="after")
    def require_feedback(self) -> Self:
        """Reject revision requests without a usable critique."""
        if self.decision == "revise" and not self.critique.strip():
            raise ValueError("Revision requires a specific critique")
        return self


class PortfolioVerdicts(BaseModel):
    """Structured response; buyer coverage is checked against runtime input."""

    model_config = ConfigDict(extra="forbid")
    verdicts: list[ReviewVerdict]


class ReviewResult(BaseModel):
    """Failure remains visible without discarding verified analyst pages."""

    model_config = ConfigDict(extra="forbid")
    verdicts: list[ReviewVerdict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


type RunId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class PageAttempt(BaseModel):
    """Validation for one generation, retained even after a successful repair."""

    model_config = ConfigDict(extra="forbid")
    stage: str
    status: Literal["verified", "failed"]
    errors: list[str]
    claims_total: NonNegativeInt
    claims_verified: NonNegativeInt


class PageResult(BaseModel):
    """A page either verifies or retains specific errors for later repair."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    acquirer: str
    acquirer_type: AcquirerType
    status: Literal["verified", "failed"]
    banner: str | None = None
    rationale: AcquirerRationale | None = None
    errors: list[str]
    tools: list[str]
    attempts: list[PageAttempt] = Field(default_factory=list)
    latency_seconds: float
    claims_total: NonNegativeInt = 0
    claims_verified: NonNegativeInt = 0


class AnalystRun(BaseModel):
    """Observed execution, without confusing replay latency or cost with live results."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    run_id: RunId
    replay_of: RunId | None = None
    source_git_sha: str | None = None
    mode: ExecutionMode
    git_sha: str
    source_dirty: bool = False
    prompt_version: str
    latency_seconds: float
    pages: list[PageResult]
    calls: list[CallRecord]
    before_review: list[PageResult] = Field(default_factory=list)
    review: ReviewResult | None = None
    uncertain_cost_bound_usd: float = 0
    tools_enabled: bool = True
    reviewer_enabled: bool = False
