"""Define portfolio critique without allowing the reviewer to rewrite facts.

Owns: Named verdicts and persisted reviewer outcomes.
Does not own: Ranking, editing pages, or claim verification.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
