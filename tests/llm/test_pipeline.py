"""Verify warm-up, bounded concurrency, and page-level failure isolation.

Owns: Observable scheduling and persistence behavior of the analyst batch.
Does not own: Live latency targets or statistical prose quality.
"""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.evidence.pack import CorePack
from acquirer_engine.llm.analyst import build_services
from acquirer_engine.llm.pipeline import run_analysts
from acquirer_engine.llm.results import PageResult
from tests.fixtures.rationale import evidence_context, rationale_payload


@pytest.mark.asyncio
async def test_first_response_warms_prefix_before_bounded_parallel_requests(
    deps: Deps, tmp_path: Path
) -> None:
    active = peak = calls = 0
    release = asyncio.Event()

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal active, peak, calls
        calls += 1
        active += 1
        peak = max(peak, active)
        if calls > 1:
            if active == 2:
                release.set()
            await asyncio.wait_for(release.wait(), 2)
        returned = any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        )
        part = (
            ToolCallPart(info.output_tools[0].name, rationale_payload())
            if returned
            else ToolCallPart(
                "get_comparable_deals",
                {"sector": "Services", "size_band": {"low": 100, "high": 400}},
            )
        )
        active -= 1
        return ModelResponse(parts=[part], usage=RequestUsage(input_tokens=100, output_tokens=20))

    context = evidence_context(deps.settings)
    deps = replace(
        deps,
        settings=deps.settings.model_copy(
            update={"analyst": deps.settings.analyst.model_copy(update={"concurrency": 2})}
        ),
    )
    runtime = build_services(
        deps,
        FunctionModel(respond),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    pages = await run_analysts([context.core] * 3, replace(deps, runtime=runtime))
    assert all(page.status == "verified" for page in pages)
    assert peak == 2 and calls == 6
    assert sorted(entry.attempt for entry in runtime.model.ledger.entries) == [1, 1, 1, 2, 2, 2]


@pytest.mark.asyncio
async def test_first_page_failure_does_not_block_later_pages(deps: Deps, tmp_path: Path) -> None:
    from tests.llm.test_analyst import tool_model

    context = evidence_context(deps.settings)
    bad = context.core.model_copy(
        update={"ranking": context.core.ranking.model_copy(update={"conviction": "Low"})}
    )
    runtime = build_services(
        deps,
        tool_model(),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    pages = await run_analysts([bad, context.core], replace(deps, runtime=runtime))
    assert [page.status for page in pages] == ["failed", "verified"]


@pytest.mark.asyncio
async def test_failed_warmup_stays_serial_until_a_response(
    deps: Deps, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import acquirer_engine.llm.pipeline as pipeline

    context = evidence_context(deps.settings)
    names = ["First", "Second", "Third", "Fourth"]
    packs = [
        context.core.model_copy(
            update={"ranking": context.core.ranking.model_copy(update={"acquirer": name})}
        )
        for name in names
    ]
    runtime = build_services(
        deps, None, context.core.deals, tmp_path, "Fixture instructions.", mode="replay"
    )
    active = peak = 0
    active_before_response = 0

    async def scheduled(pack: CorePack, _: Deps) -> PageResult:
        nonlocal active, active_before_response, peak
        active += 1
        peak = max(peak, active)
        name = pack.ranking.acquirer
        if name == "First":
            active -= 1
            return PageResult.model_construct(acquirer=name, status="failed")
        if name == "Second":
            await asyncio.sleep(0)
            active_before_response = active
            runtime.model.first_response.set()
        await asyncio.sleep(0)
        active -= 1
        return PageResult.model_construct(acquirer=name, status="verified")

    monkeypatch.setattr(pipeline, "analyze_one", scheduled)
    pages = await run_analysts(packs, replace(deps, runtime=runtime))
    assert [page.status for page in pages] == ["failed", "verified", "verified", "verified"]
    assert active_before_response == 1
    assert peak == 2
