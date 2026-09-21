"""Represent verified pages and explicit failed-page outcomes.

Owns: Typed per-page and per-run artifacts with observed usage.
Does not own: Rendering or judging narrative quality.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from acquirer_engine.data.schema import AcquirerType
from acquirer_engine.llm.cost import CallRecord, ExecutionMode
from acquirer_engine.validation.schema import AcquirerRationale


class PageResult(BaseModel):
    """A page either verifies or retains specific errors for later repair."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    acquirer: str
    acquirer_type: AcquirerType
    status: Literal["verified", "failed"]
    rationale: AcquirerRationale | None = None
    errors: list[str]
    tools: list[str]
    latency_seconds: float
    claims_total: NonNegativeInt = 0
    claims_verified: NonNegativeInt = 0


class AnalystRun(BaseModel):
    """Observed execution, without confusing replay latency or cost with live results."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    mode: ExecutionMode
    git_sha: str
    prompt_version: str
    latency_seconds: float
    pages: list[PageResult]
    calls: list[CallRecord]
