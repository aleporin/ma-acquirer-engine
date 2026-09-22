"""Select recorded model responses from one historical run.

Owns: Exchange identity, conversation matching, and explicit incomplete archives.
Does not own: Network access, shared-cache lookup, or new model generation.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, PositiveInt, ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse

from acquirer_engine.errors import (
    BudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
)
from acquirer_engine.llm.cache import request_key
from acquirer_engine.llm.results import PageAttempt
from acquirer_engine.llm.review_schema import ReviewResult


class RequestFailure(BaseModel):
    """Safe application failure metadata, separate from a model response or charge."""

    kind: Literal["budget", "timeout", "rate_limit", "provider", "invalid_output"]
    message: str

    @classmethod
    def from_error(cls, error: BudgetExceeded | LLMError) -> "RequestFailure":
        """Encode a typed application error without raw provider payloads."""
        kinds = {
            BudgetExceeded: "budget",
            LLMTimeout: "timeout",
            LLMRateLimited: "rate_limit",
            LLMInvalidOutput: "invalid_output",
            LLMError: "provider",
        }
        return cls.model_validate({"kind": kinds[type(error)], "message": str(error)})

    def exception(self) -> BudgetExceeded | LLMError:
        """Restore the original application exception for offline control flow."""
        types: dict[str, type[BudgetExceeded] | type[LLMError]] = {
            "budget": BudgetExceeded,
            "timeout": LLMTimeout,
            "rate_limit": LLMRateLimited,
            "invalid_output": LLMInvalidOutput,
            "provider": LLMError,
        }
        return types[self.kind](self.message)


class ArchivedFailure(BaseModel):
    """A request ended without a response; replay must preserve its reason."""

    acquirer: str
    attempt: PositiveInt
    failure: RequestFailure


class ArchivedRequest(BaseModel):
    """Only the request fields needed for deterministic conversation matching."""

    event: Literal["model_requested"]
    acquirer: str
    attempt: PositiveInt
    messages: list[ModelMessage]


class ArchivedResponse(BaseModel):
    """Raw response and usage, including outputs rejected by validation."""

    event: Literal["model_responded"]
    acquirer: str
    attempt: PositiveInt
    response: ModelResponse


@dataclass
class Exchange:
    """A request may have no response when its original execution failed."""

    fingerprint: str
    response: ModelResponse | None = None
    failure: RequestFailure | None = None


class ResponseArchive:
    """Responses scoped by buyer and request number, never by task scheduling order."""

    def __init__(self, exchanges: dict[tuple[str, int], Exchange]) -> None:
        """Inject the recorded exchanges once before replay fan-out."""
        self.exchanges = exchanges

    @classmethod
    def from_trace(cls, path: Path, *, report_path: Path | None = None) -> "ResponseArchive":
        """Read a transcript without consulting the replaceable request cache.

        Args:
            path: Original run's trace.jsonl file.
            report_path: Optional matching report for legacy reviewer failure evidence.
        Returns:
            Typed request/response exchanges for exactly this run.
        Raises:
            LLMInvalidOutput: Transcript is corrupt or has ambiguous exchanges.
        """
        exchanges: dict[tuple[str, int], Exchange] = {}
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("Trace event is not an object")
                    _record_event(exchanges, event)
            if report_path is not None:
                _restore_review_failure(exchanges, report_path)
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise LLMInvalidOutput("Invalid response archive") from error
        return cls(exchanges)

    def load(self, buyer: str, attempt: int, messages: list[ModelMessage]) -> ModelResponse:
        """Return the original answer only when the replayed conversation matches.

        Args:
            buyer: Page identity.
            attempt: Per-page framework request number.
            messages: Current conversation after deterministic tool execution.
        Returns:
            Original response with historical usage, never a later cached answer.
        Raises:
            LLMInvalidOutput: A response is absent or the request differs.
        """
        exchange = self.exchanges.get((buyer, attempt))
        if exchange is None:
            raise LLMInvalidOutput(f"Archived request missing for {buyer}, attempt {attempt}")
        if exchange.fingerprint != request_key("", messages, {}):
            raise LLMInvalidOutput(f"Archived request differs for {buyer}, attempt {attempt}")
        if exchange.failure is not None:
            raise exchange.failure.exception()
        if exchange.response is None:
            raise LLMInvalidOutput(f"Archived response missing for {buyer}, attempt {attempt}")
        return exchange.response


def _record_event(exchanges: dict[tuple[str, int], Exchange], event: dict[str, object]) -> None:
    if event.get("event") == "model_requested":
        request = ArchivedRequest.model_validate(event)
        key = (request.acquirer, request.attempt)
        if key in exchanges:
            raise ValueError("Duplicate archived request")
        exchanges[key] = Exchange(request_key("", request.messages, {}))
    elif event.get("event") == "model_responded":
        response = ArchivedResponse.model_validate(event)
        key = (response.acquirer, response.attempt)
        if key not in exchanges or exchanges[key].response is not None or exchanges[key].failure:
            raise ValueError("Orphan or duplicate archived response")
        exchanges[key].response = response.response
    elif event.get("event") == "model_failed":
        failed = ArchivedFailure.model_validate(event)
        key = (failed.acquirer, failed.attempt)
        if key not in exchanges or exchanges[key].response is not None or exchanges[key].failure:
            raise ValueError("Orphan or duplicate archived failure")
        exchanges[key].failure = failed.failure
    elif event.get("event") == "validation_completed":
        attempt = PageAttempt.model_validate(event["attempt"])
        if attempt.status == "failed" and attempt.claims_total == 0:
            _restore_failure(exchanges, str(event["acquirer"]), attempt.errors)


def _restore_failure(
    exchanges: dict[tuple[str, int], Exchange], buyer: str, errors: list[str]
) -> None:
    known = {
        "Run USD budget cannot admit another request": "budget",
        "Run deadline exceeded": "timeout",
        "Model request timed out": "timeout",
        "Model request rate limited": "rate_limit",
    }
    if len(errors) != 1 or errors[0] not in known:
        return
    keys = [key for key in exchanges if key[0] == buyer]
    if not keys:
        return
    exchange = exchanges[max(keys, key=lambda key: key[1])]
    if exchange.response is None and exchange.failure is None:
        exchange.failure = RequestFailure.model_validate(
            {"kind": known[errors[0]], "message": errors[0]}
        )


class ArchivedReview(BaseModel):
    """Read historical reviewer errors without reparsing old rationale schemas."""

    run_id: str
    review: ReviewResult | None = None


def _restore_review_failure(exchanges: dict[tuple[str, int], Exchange], path: Path) -> None:
    report = ArchivedReview.model_validate_json(path.read_bytes())
    if report.run_id != path.parent.name:
        raise ValueError("Reviewer report identity differs from its directory")
    if report.review and report.review.errors:
        _restore_failure(exchanges, "portfolio", report.review.errors)
