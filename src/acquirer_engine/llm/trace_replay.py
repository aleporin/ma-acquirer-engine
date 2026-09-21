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

from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.llm.cache import request_key


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


class ResponseArchive:
    """Responses scoped by buyer and request number, never by task scheduling order."""

    def __init__(self, exchanges: dict[tuple[str, int], Exchange]) -> None:
        """Inject the recorded exchanges once before replay fan-out."""
        self.exchanges = exchanges

    @classmethod
    def from_trace(cls, path: Path) -> "ResponseArchive":
        """Read a transcript without consulting the replaceable request cache.

        Args:
            path: Original run's trace.jsonl file.
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
        if key not in exchanges or exchanges[key].response is not None:
            raise ValueError("Orphan or duplicate archived response")
        exchanges[key].response = response.response
