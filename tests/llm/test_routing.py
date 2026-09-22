"""Exercise routing decisions through injected model conversations.

Owns: Escalation limits, sparse evidence, and tools-disabled failure.
Does not own: Live model quality or portfolio review.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.factory import build_services
from acquirer_engine.stages.draft import draft_one
from tests.fixtures.rationale import evidence_context, rationale_payload
from tests.llm.test_repair import correcting_model


def routing_deps(deps: Deps, **updates: object) -> Deps:
    config = deps.settings.analyst.model_copy(
        update={
            "max_repairs": 2,
            "escalation_enabled": True,
            **updates,
        }
    )
    return replace(deps, settings=deps.settings.model_copy(update={"analyst": config}))


@pytest.mark.asyncio
@pytest.mark.parametrize("escalation_valid", [True, False])
async def test_second_failure_escalates_once_then_passes_or_banners(
    deps: Deps, tmp_path: Path, escalation_valid: bool
) -> None:
    deps = routing_deps(deps)
    context = evidence_context(deps.settings)

    async def escalated(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raw = rationale_payload()
        if not escalation_valid:
            raw["risk_flags"] = []
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, raw)],
            usage=RequestUsage(input_tokens=100, output_tokens=30),
        )

    runtime = cast(Any, build_services)(
        deps,
        correcting_model("schema", [], correct=False),
        context.core.deals + context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
        escalation_model=FunctionModel(escalated),
    )
    page = await draft_one(context.core, deps.with_runtime(runtime))
    assert page.status == ("verified" if escalation_valid else "failed")
    assert [a.stage for a in page.attempts] == ["analyst", "repair", "escalation"]
    calls = runtime.model.ledger.entries
    assert len(calls) == 4
    assert calls[-1].model == deps.settings.models.roles["escalation"].model_id
    assert calls[-1].stage == "escalation"
    assert bool(page.model_dump()["banner"]) is not escalation_valid


@pytest.mark.asyncio
@pytest.mark.parametrize("relevant,expect_sparse", [(2, True), (3, False)])
async def test_sparse_route_uses_ranked_density_not_truncated_pack_rows(
    deps: Deps, tmp_path: Path, relevant: int, expect_sparse: bool
) -> None:
    deps = routing_deps(deps, sparse_prompt_file="analyst_sparse_v1.md", sparse_relevant_deals=3)
    context = evidence_context(deps.settings)
    pack = context.core.model_copy(
        update={"ranking": context.core.ranking.model_copy(update={"relevant_deals": relevant})}
    )
    instructions = []

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        instructions.append(info.instructions)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, rationale_payload())],
            usage=RequestUsage(input_tokens=100, output_tokens=30),
        )

    runtime = cast(Any, build_services)(
        deps,
        FunctionModel(answer),
        (),
        tmp_path,
        "Standard route.",
        mode="test",
        auxiliary_prompts={"sparse": "Sparse route requires hedging."},
    )
    await draft_one(pack, deps.with_runtime(runtime))
    assert ("Sparse route requires hedging." in (instructions[0] or "")) is expect_sparse


@pytest.mark.asyncio
async def test_tools_disabled_cannot_validate_invented_comp_provenance(
    deps: Deps, tmp_path: Path
) -> None:
    deps = routing_deps(deps, tools_enabled=False, max_repairs=0)
    context = evidence_context(deps.settings)

    async def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert not info.function_tools
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, rationale_payload())],
            usage=RequestUsage(input_tokens=100, output_tokens=30),
        )

    runtime = cast(Any, build_services)(
        deps,
        FunctionModel(answer),
        context.comparable_deals,
        tmp_path,
        "Fixture instructions.",
        mode="test",
    )
    page = await draft_one(context.core, deps.with_runtime(runtime))
    assert page.status == "failed"
    assert any("comps" in error or "comp" in error for error in page.errors)
