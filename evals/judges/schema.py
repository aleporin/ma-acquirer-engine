"""Define frozen judge inputs and independent verdict contracts.

Owns: Case provenance, corpus integrity, dimensions, and structured answers.
Does not own: Prompt execution, page generation, or agreement calculations.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

type Vote = Literal["Pass", "Fail", "Unknown"]
type Text = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    """Reject unexpected fields and freeze evaluation boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Dimension(StrEnum):
    """The five independently judged page qualities."""

    SPECIFICITY = "specificity"
    THESIS = "thesis_evidence_link"
    RISK = "risk_relevance"
    CONVICTION = "conviction_defensibility"
    TONE = "banker_tone"


class Candidate(Record):
    """Named evidence summary without a suggested identification answer."""

    name: Text
    summary: Text


class Case(Record):
    """One visible page and its evidence, independent of later generation changes."""

    case_id: Annotated[str, Field(pattern=r"^case-[0-9a-f]{16}$")]
    source_run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    source_git_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    generation_prompt: Text
    buyer: Text
    stage: Literal["before_review", "after_review"]
    reviewer_enabled: bool
    page: Text
    evidence: Text
    target: Text
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_candidates(self) -> Self:
        names = [candidate.name for candidate in self.candidates]
        if len(set(names)) != len(names) or names.count(self.buyer) != 1:
            raise ValueError("Candidates must be unique and contain the page's buyer once")
        return self


def corpus_digest(cases: tuple[Case, ...], seed: int) -> str:
    """Bind the complete inputs and shuffle policy to a portable digest."""
    payload = {"seed": seed, "cases": [case.model_dump(mode="json") for case in cases]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Corpus(Record):
    """Tamper-evident collection; source cohorts remain visible per case."""

    digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    seed: int
    cases: Annotated[tuple[Case, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def check_integrity(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case identity")
        if self.digest != corpus_digest(self.cases, self.seed):
            raise ValueError("Corpus digest does not match its inputs")
        return self


class RubricAnswer(Record):
    """One rubric dimension, with an explicit abstention option."""

    reason: Text
    vote: Vote


class IdentificationAnswer(Record):
    """One candidate position; None means the page cannot be identified."""

    reason: Text
    choice: PositiveInt | None


class HumanLabel(Record):
    """One human judgment, never inferred from another judge's output."""

    case_id: Text
    dimension: Dimension
    vote: Vote
