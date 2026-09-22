"""Bound portfolio critique to one validated revision and preserve replay inputs.

Owns: Verdict identity checks, pre-review provenance, and revision outcomes.
Does not own: Live reviewer quality or calibration against human labels.
"""

from pathlib import Path

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.pipeline import execute_prepared, execute_replay
from tests.fixtures.rationale import rationale_payload
from tests.llm.test_routing import routing_deps
from tests.llm.test_run_archive import inputs


def review_model(*, bad_revision: bool = False, wrong_buyer: bool = False) -> FunctionModel:
    calls = 0

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            part = ToolCallPart(
                "get_comparable_deals",
                {"sector": "Services", "size_band": {"low": 100, "high": 400}},
            )
        elif calls == 3:
            part = ToolCallPart(
                info.output_tools[0].name,
                {
                    "verdicts": [
                        {
                            "acquirer": "Unknown" if wrong_buyer else "Buyer A",
                            "decision": "revise",
                            "critique": "Explain why the integration risk limits the fit thesis.",
                        }
                    ]
                },
            )
        else:
            raw = rationale_payload()
            if calls > 3:
                assert "integration risk limits" in str(messages)
                if bad_revision:
                    raw["reasoning"] = "Margin is 71%."
            part = ToolCallPart(info.output_tools[0].name, raw)
        return ModelResponse(parts=[part], usage=RequestUsage(input_tokens=100, output_tokens=30))

    return FunctionModel(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_revision", [False, True])
async def test_reviewer_allows_one_revision_and_revalidates_without_losing_original(
    deps: Deps, tmp_path: Path, bad_revision: bool
) -> None:
    deps = routing_deps(deps, reviewer_enabled=True, reviewer_prompt_file="reviewer_v1.md")
    snapshot = inputs(deps, "b" * 32).model_copy(
        update={"auxiliary_prompts": {"reviewer": "Review every page and return a verdict."}}
    )
    directory = tmp_path / snapshot.run_id
    result = await execute_prepared(
        snapshot, directory, deps, mode="test", model=review_model(bad_revision=bad_revision)
    )
    raw = result.model_dump()
    assert raw["before_review"][0]["status"] == "verified"
    assert result.pages[0].status == ("failed" if bad_revision else "verified")
    assert [c.stage for c in result.calls] == ["analyst", "analyst", "reviewer", "revision"]
    assert [c.attempt for c in result.calls if c.acquirer == "Buyer A"] == [1, 2, 3]
    assert raw["review"]["verdicts"][0]["decision"] == "revise"
    replay = await execute_replay(directory, tmp_path / ("c" * 32), snapshot, deps, "d" * 40)
    assert len(replay.calls) == 4
    assert replay.pages[0].status == result.pages[0].status
    assert replay.pages[0].errors == result.pages[0].errors
    assert sum(c.cost_usd for c in replay.calls) == 0


@pytest.mark.asyncio
async def test_reviewer_rejects_verdicts_for_unknown_buyers(deps: Deps, tmp_path: Path) -> None:
    deps = routing_deps(deps, reviewer_enabled=True, reviewer_prompt_file="reviewer_v1.md")
    snapshot = inputs(deps, "b" * 32).model_copy(
        update={"auxiliary_prompts": {"reviewer": "Review every page and return a verdict."}}
    )
    result = await execute_prepared(
        snapshot,
        tmp_path / snapshot.run_id,
        deps,
        mode="test",
        model=review_model(wrong_buyer=True),
    )
    assert len(result.calls) == 3
    assert "exactly once" in " ".join(result.model_dump()["review"]["errors"])
    assert result.pages[0].status == "verified"
