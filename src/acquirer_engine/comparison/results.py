"""Represent a saved comparison independently of buyer-page output.

Owns: Computed facts, feedback provenance, optional interpretation, and usage.
Does not own: Execution or rendering.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from acquirer_engine.comparison.ranking import ComparisonData
from acquirer_engine.feedback.ranking import FeedbackPolicy
from acquirer_engine.feedback.state import FeedbackState
from acquirer_engine.llm.cost import CallRecord
from acquirer_engine.llm.results import RunId


class ComparisonRun(BaseModel):
    """Preserve computed output even when the optional summary fails."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: RunId
    git_sha: str
    source_dirty: bool
    mode: Literal["ranking-only", "replay", "live"]
    data: ComparisonData
    feedback: FeedbackState
    feedback_policy: FeedbackPolicy
    summary: str | None = None
    errors: tuple[str, ...] = ()
    calls: tuple[CallRecord, ...] = ()
    uncertain_cost_bound_usd: float = 0
    prompt_file: str | None = None
    latency_seconds: float = 0
