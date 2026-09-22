"""Specify request accounting, replay isolation, and cache identity.

Owns: Real usage arithmetic and deterministic offline request replay.
Does not own: Provider billing verification or live network access.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.errors import LLMInvalidOutput
from acquirer_engine.llm.cache import ResponseCache, request_key
from acquirer_engine.llm.cost import CostLedger
from acquirer_engine.llm.recording import RecordedModel
from acquirer_engine.llm.trace import TraceWriter
from acquirer_engine.settings import ModelSpec


def test_usage_separates_cached_input_from_uncached_input(accounting_model: ModelSpec) -> None:
    ledger = CostLedger(accounting_model)
    usage = RequestUsage(
        input_tokens=200, output_tokens=20, cache_read_tokens=70, cache_write_tokens=30
    )
    entry = ledger.record("Buyer A", 1, usage, 12.5, mode="live")
    assert entry.cost_usd == pytest.approx((100 * 2 + 20 * 10 + 70 * 0.2 + 30 * 2.5) / 1_000_000)
    assert entry.input_tokens == 200 and entry.cache_write_tokens == 30
    assert ledger.cost_usd == entry.cost_usd
    with pytest.raises(LLMInvalidOutput, match="zero tokens"):
        ledger.record("Buyer A", 2, RequestUsage(), 1, mode="live")


def test_cache_key_ignores_timestamps_but_includes_evidence_settings_and_tools() -> None:
    first = [{"kind": "request", "timestamp": "earlier", "content": "evidence A"}]
    second = [{"kind": "request", "timestamp": "later", "content": "evidence A"}]
    assert request_key("model/config/schema/prompt", first, {"tools": "v1"}) == request_key(
        "model/config/schema/prompt", second, {"tools": "v1"}
    )
    assert request_key("identity", first, {}) != request_key(
        "identity", [{"content": "evidence B"}], {}
    )
    assert request_key("identity", first, {}) != request_key("changed identity", first, {})
    assert request_key("identity", first, {}) != request_key(
        "identity", first, {"tools": "changed"}
    )


@pytest.mark.asyncio
async def test_replay_uses_no_model_and_records_zero_new_cost(deps: Deps, tmp_path: Path) -> None:
    calls: list[list[ModelMessage]] = []

    async def response(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        return ModelResponse(
            parts=[TextPart("Recorded answer")],
            usage=RequestUsage(input_tokens=100, output_tokens=5),
        )

    cache = ResponseCache(tmp_path / "cache")
    ledger = CostLedger(deps.settings.models.roles["analyst"])
    model = RecordedModel(
        FunctionModel(response),
        deps,
        cache,
        ledger,
        TraceWriter(tmp_path / "trace.jsonl"),
        mode="test",
    )
    parameters = ModelRequestParameters()
    with model.scope("Buyer A"):
        original = await model.request(
            [ModelRequest(parts=[UserPromptPart("Question")])], None, parameters
        )
    replay_ledger = CostLedger(deps.settings.models.roles["analyst"])
    replay = RecordedModel(
        None, deps, cache, replay_ledger, TraceWriter(tmp_path / "replay.jsonl"), mode="replay"
    )
    with replay.scope("Buyer A"):
        result = await replay.request(
            [
                ModelRequest(
                    parts=[UserPromptPart("Question", timestamp=datetime(2000, 1, 1, tzinfo=UTC))]
                )
            ],
            None,
            parameters,
        )
    assert result.parts == original.parts and len(calls) == 1
    assert replay_ledger.cost_usd == 0
    assert replay_ledger.entries[0].input_tokens == 100
    assert replay_ledger.entries[0].mode == "replay"
    assert "Recorded answer" in (tmp_path / "trace.jsonl").read_text()
