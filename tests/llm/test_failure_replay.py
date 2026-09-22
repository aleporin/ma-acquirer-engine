"""Preserve failed request outcomes without inventing provider responses.

Owns: Offline replay of budget denials, timeouts, and legacy failure evidence.
Does not own: Provider invoices or successful generation quality.
"""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from acquirer_engine.deps import Deps
from acquirer_engine.errors import BudgetExceeded, LLMInvalidOutput
from acquirer_engine.llm.trace import ResponseArchive, TraceWriter
from acquirer_engine.pipeline import execute_prepared, execute_replay
from tests.llm.test_routing import routing_deps
from tests.llm.test_run_archive import inputs
from tests.llm.test_trace_replay import exchange


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["budget", "timeout", "deadline"])
async def test_failed_generation_and_reviewer_replay_the_original_errors(
    deps: Deps, tmp_path: Path, failure: str
) -> None:
    deps = routing_deps(
        deps,
        max_run_usd=0.000001 if failure == "budget" else None,
        request_timeout_seconds=0.01 if failure == "timeout" else 1,
        run_timeout_seconds=0.01 if failure == "deadline" else None,
        reviewer_enabled=True,
    )
    snapshot = inputs(deps, "b" * 32).model_copy(
        update={"auxiliary_prompts": {"reviewer": "Review the supplied pages."}}
    )

    async def fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert failure != "budget", "Denied requests must never reach the provider"
        await asyncio.sleep(1)
        raise AssertionError("Timeout must interrupt the provider")

    original = tmp_path / snapshot.run_id
    live = await execute_prepared(snapshot, original, deps, model=FunctionModel(fail), mode="live")
    frozen = {p.name: p.read_bytes() for p in original.iterdir() if p.is_file()}
    events = [json.loads(line) for line in (original / "trace.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "model_failed" for e in events) == 2
    replay = await execute_replay(original, tmp_path / ("c" * 32), snapshot, deps, "d" * 40)
    assert replay.pages[0].errors == live.pages[0].errors
    assert replay.pages[0].attempts == live.pages[0].attempts
    assert replay.review == live.review
    assert replay.calls == []
    assert {p.name: p.read_bytes() for p in original.iterdir() if p.is_file()} == frozen


def test_legacy_validation_proves_a_missing_request_failed_for_budget(tmp_path: Path) -> None:
    trace = TraceWriter(tmp_path / "trace.jsonl")
    exchange(trace, "Buyer", None)
    trace.write(
        "validation_completed",
        "Buyer",
        attempt={
            "stage": "analyst",
            "status": "failed",
            "errors": ["Run USD budget cannot admit another request"],
            "claims_total": 0,
            "claims_verified": 0,
        },
    )
    archive = ResponseArchive.from_trace(trace.path)
    with pytest.raises(BudgetExceeded, match="Run USD budget"):
        archive.load("Buyer", 1, [ModelRequest(parts=[UserPromptPart("Original question")])])


def test_a_failure_event_cannot_replace_a_returned_response(tmp_path: Path) -> None:
    trace = TraceWriter(tmp_path / "trace.jsonl")
    exchange(trace, "Buyer", "Answer")
    trace.write(
        "model_failed",
        "Buyer",
        attempt=1,
        failure={"kind": "budget", "message": "Run USD budget cannot admit another request"},
    )
    with pytest.raises(LLMInvalidOutput, match="archive"):
        ResponseArchive.from_trace(trace.path)
