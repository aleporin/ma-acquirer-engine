"""Prevent overspending and isolate provider failures without network access.

Owns: Shared reservations, deadlines, output limits, and failure classification.
Does not own: Reconciling provider invoices or testing live availability.
"""

import asyncio
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.errors import BudgetExceeded
from acquirer_engine.llm.analyst import analyze_one, build_services
from tests.fixtures.rationale import evidence_context, rationale_payload
from tests.llm.test_routing import routing_deps


@pytest.mark.asyncio
async def test_shared_budget_waits_for_inflight_reservations_and_reconciles_usage() -> None:
    budget = import_module("acquirer_engine.llm.budget").RunBudget(1.0)
    await budget.reserve(0.7)
    waiting = asyncio.create_task(budget.reserve(0.7))
    await asyncio.sleep(0)
    assert not waiting.done()
    await budget.settle(0.7, 0.2)
    await asyncio.wait_for(waiting, 1)
    await budget.settle(0.7, 0.6)
    with pytest.raises(BudgetExceeded):
        await budget.reserve(0.3)


@pytest.mark.asyncio
async def test_uncertain_failed_request_retains_its_reservation() -> None:
    budget = import_module("acquirer_engine.llm.budget").RunBudget(1.0)
    await budget.reserve(0.7)
    await budget.settle(0.7, None)
    with pytest.raises(BudgetExceeded):
        await budget.reserve(0.4)


@pytest.mark.asyncio
async def test_usd_guard_prevents_a_request_before_model_execution(
    deps: Deps, tmp_path: Path
) -> None:
    deps = routing_deps(deps, max_run_usd=0.000001)
    context = evidence_context(deps.settings)

    async def never(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        pytest.fail("Budget breach must be caught before the provider call")

    runtime = build_services(deps, FunctionModel(never), (), tmp_path, "Fixture.", mode="live")
    page = await analyze_one(context.core, replace(deps, runtime=runtime))
    assert page.status == "failed" and "budget" in " ".join(page.errors).lower()
    assert not runtime.model.ledger.entries
    assert len(page.attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "deadline", "429", "tokens"])
async def test_provider_failures_are_not_retried_as_validation_repairs(
    deps: Deps, tmp_path: Path, failure: str
) -> None:
    deps = routing_deps(
        deps,
        request_timeout_seconds=1 if failure == "deadline" else 0.01,
        run_timeout_seconds=0.01 if failure == "deadline" else None,
    )
    context = evidence_context(deps.settings)
    calls = 0

    async def failing(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if failure in {"timeout", "deadline"}:
            await asyncio.sleep(1)
        if failure == "429":
            raise ModelHTTPError(429, "fixture")
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, rationale_payload())],
            usage=RequestUsage(
                input_tokens=100, output_tokens=deps.settings.analyst.max_output_tokens + 1
            ),
        )

    runtime = build_services(deps, FunctionModel(failing), (), tmp_path, "Fixture.", mode="test")
    page = await analyze_one(context.core, replace(deps, runtime=runtime))
    assert page.status == "failed"
    assert calls == 1 and len(page.attempts) == 1
    if failure == "tokens":
        assert "token" in " ".join(page.errors).lower()
        assert len(runtime.model.ledger.entries) == 1
