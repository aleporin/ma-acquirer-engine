"""Specify strict response selection from a run's recorded exchanges.

Owns: Conversation identity, missing responses, and malformed archive rejection.
Does not own: Live transport or generation under a revised prompt.
"""

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.llm.trace import TraceWriter
from acquirer_engine.llm.trace_replay import ResponseArchive


def exchange(trace: TraceWriter, buyer: str, reply: str | None) -> None:
    trace.write(
        "model_requested",
        buyer,
        attempt=1,
        cache_key="irrelevant",
        messages=[ModelRequest(parts=[UserPromptPart("Original question")])],
    )
    if reply is not None:
        trace.write(
            "model_responded",
            buyer,
            attempt=1,
            response=ModelResponse(parts=[TextPart(reply)]),
        )


def test_archived_responses_are_selected_by_buyer_and_attempt(tmp_path: Path) -> None:
    trace = TraceWriter(tmp_path / "trace.jsonl")
    exchange(trace, "Buyer A", "Answer A")
    exchange(trace, "Buyer B", "Answer B")
    archive = ResponseArchive.from_trace(trace.path)
    messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("Original question")])]
    assert archive.load("Buyer B", 1, messages).parts == [TextPart("Answer B")]
    assert archive.load("Buyer A", 1, messages).parts == [TextPart("Answer A")]
    with pytest.raises(LLMInvalidOutput, match="differs"):
        archive.load("Buyer A", 1, [ModelRequest(parts=[UserPromptPart("Changed question")])])
    with pytest.raises(LLMInvalidOutput, match="missing"):
        archive.load("Buyer A", 2, messages)


def test_missing_response_stays_missing_even_when_another_run_has_it(tmp_path: Path) -> None:
    first = TraceWriter(tmp_path / "first.jsonl")
    second = TraceWriter(tmp_path / "second.jsonl")
    exchange(first, "Buyer", None)
    exchange(second, "Buyer", "Later answer")
    archive = ResponseArchive.from_trace(first.path)
    with pytest.raises(LLMInvalidOutput, match="response missing"):
        archive.load("Buyer", 1, [ModelRequest(parts=[UserPromptPart("Original question")])])


@pytest.mark.parametrize(
    "corruption", ["duplicate", "invalid_json", "orphan_response", "invalid_validation"]
)
def test_corrupt_archives_fail_explicitly(tmp_path: Path, corruption: str) -> None:
    trace = TraceWriter(tmp_path / "trace.jsonl")
    exchange(trace, "Buyer", "Answer")
    if corruption == "duplicate":
        exchange(trace, "Buyer", "Replacement")
    elif corruption == "invalid_json":
        with trace.path.open("a") as stream:
            stream.write("broken\n")
    elif corruption == "invalid_validation":
        trace.write("validation_completed", "Buyer")
    else:
        trace.write("model_responded", "Other", attempt=1, response=ModelResponse(parts=[]))
    with pytest.raises(LLMInvalidOutput, match="archive"):
        ResponseArchive.from_trace(trace.path)
