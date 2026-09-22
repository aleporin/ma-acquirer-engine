"""Check token-aware admission and distinguish waiting from provider latency.

Owns: Counted reservations, conservative fallback, offline isolation, and timing.
Does not own: Live tokenizer accuracy or provider performance claims.
"""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from acquirer_engine.bootstrap import build_services
from acquirer_engine.deps import Deps
from acquirer_engine.errors import BudgetExceeded
from tests.llm.test_routing import routing_deps


class CountedModel(FunctionModel):
    """An injected counting endpoint and clock with no network access."""

    def __init__(self, *, available: bool = True) -> None:
        super().__init__(self.answer)
        self.available = available
        self.counts = self.answers = 0
        self.clock = 0.0

    async def count_tokens(
        self,
        messages: list[ModelMessage],
        settings: ModelSettings | None,
        parameters: ModelRequestParameters,
    ) -> RequestUsage:
        self.counts += 1
        self.clock += 2
        if not self.available:
            raise NotImplementedError("No counting endpoint")
        return RequestUsage(input_tokens=100)

    async def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.answers += 1
        self.clock += 5
        return ModelResponse(
            parts=[TextPart("OK")], usage=RequestUsage(input_tokens=100, output_tokens=1)
        )


def conversation() -> list[ModelMessage]:
    return [ModelRequest(parts=[UserPromptPart("Known tokenizer input " * 2000)])]


@pytest.mark.asyncio
async def test_counted_input_admits_a_request_that_byte_reservations_reject(
    accounting_deps: Deps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps = routing_deps(accounting_deps, count_input_tokens=True, max_run_usd=0.02)
    model = CountedModel()
    monkeypatch.setattr("acquirer_engine.llm.recording.perf_counter", lambda: model.clock)
    runtime = build_services(deps, model, (), tmp_path, "Fixture.", mode="live")
    reserve = runtime.model.budget.reserve

    async def waiting(amount: float) -> None:
        await reserve(amount)
        model.clock += 3

    monkeypatch.setattr(runtime.model.budget, "reserve", waiting)
    with runtime.model.scope("Buyer"):
        await runtime.model.request(conversation(), {"max_tokens": 2}, ModelRequestParameters())
    assert model.counts == model.answers == 1
    call = runtime.model.ledger.entries[0]
    assert call.input_tokens == 100
    assert call.latency_ms == 10000
    assert call.model_dump()["timing"] == {
        "token_count_ms": 2000,
        "admission_ms": 3000,
        "provider_ms": 5000,
    }
    events = [json.loads(line) for line in runtime.trace.path.read_text().splitlines()]
    estimate = next(e for e in events if e["event"] == "budget_estimated")
    assert estimate["method"] == "counted"
    assert estimate["input_tokens"] == 1124
    assert estimate["reservation_usd"] == pytest.approx(0.00849)
    assert runtime.model.budget.reserved == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_counting_never_bypasses_an_insufficient_budget(
    deps: Deps, tmp_path: Path, available: bool
) -> None:
    deps = routing_deps(deps, count_input_tokens=True, max_run_usd=0.00001)
    model = CountedModel(available=available)
    runtime = build_services(deps, model, (), tmp_path, "Fixture.", mode="live")
    with runtime.model.scope("Buyer"), pytest.raises(BudgetExceeded):
        await runtime.model.request(conversation(), {"max_tokens": 2}, ModelRequestParameters())
    assert model.counts == 1 and model.answers == 0
    assert runtime.model.ledger.entries == []
    assert runtime.model.budget.uncertain == 0


@pytest.mark.asyncio
async def test_counting_is_never_called_in_test_or_replay_mode(deps: Deps, tmp_path: Path) -> None:
    deps = routing_deps(deps, count_input_tokens=True, max_run_usd=0.02)
    model = CountedModel()
    first = build_services(deps, model, (), tmp_path, "Fixture.", mode="test")
    with first.model.scope("Buyer"):
        response = await first.model.request(
            conversation(), {"max_tokens": 2}, ModelRequestParameters()
        )
    replay = build_services(deps, model, (), tmp_path, "Fixture.", mode="replay")
    with replay.model.scope("Buyer"):
        assert (
            await replay.model.request(conversation(), {"max_tokens": 2}, ModelRequestParameters())
            == response
        )
    assert model.counts == 0 and model.answers == 1
    assert replay.model.ledger.cost_usd == 0
