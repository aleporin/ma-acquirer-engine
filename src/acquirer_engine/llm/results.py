"""Represent verified pages and explicit failed-page outcomes.

Owns: Typed per-page and per-run artifacts with observed usage.
Does not own: Rendering or judging narrative quality.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from acquirer_engine.data.schema import AcquirerType
from acquirer_engine.llm.cost import CallRecord, ExecutionMode
from acquirer_engine.llm.review_schema import ReviewResult
from acquirer_engine.validation.schema import AcquirerRationale

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
