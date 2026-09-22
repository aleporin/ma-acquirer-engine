"""Store judge outcomes separately from generation costs and human labels.

Owns: Typed request failures, answered verdicts, and run accounting.
Does not own: Provider execution or agreement grading.
"""

from typing import Self

from pydantic import model_validator

from acquirer_engine.llm.cost import CallRecord, ExecutionMode
from evals.judges.schema import IdentificationAnswer, Record, RubricAnswer


class Outcome(Record):
    """An unsuccessful request is not a valid Unknown judgment."""

    job_id: str
    answer: RubricAnswer | IdentificationAnswer | None = None
    error: str | None = None
    cache_hit: bool = False
    calls: tuple[CallRecord, ...] = ()

    @model_validator(mode="after")
    def check_answer(self) -> Self:
        if (self.answer is None) == (self.error is None):
            raise ValueError("Outcome must contain an answer or an explicit failure")
        return self


class JudgeRun(Record):
    """One execution or replay of a sealed plan."""

    plan_digest: str
    mode: ExecutionMode
    outcomes: tuple[Outcome, ...]
    uncertain_cost_bound_usd: float
    git_sha: str | None = None
    source_dirty: bool = False

    @property
    def cost_usd(self) -> float:
        return sum(call.cost_usd for outcome in self.outcomes for call in outcome.calls)
