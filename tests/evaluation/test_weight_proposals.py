"""Specify a single recorded proposal request with strict offline replay.

Owns: Request count, output bounds, zero-cost replay, and rejection without retries.
Does not own: Live provider access or predictive validation of proposed weights.
"""

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from acquirer_engine.deps import Deps
from acquirer_engine.factory import build_services
from tests.evaluation.test_weighting import module_and_policy


def assert_weight_fields(schema: dict[str, Any], features: set[str]) -> None:
    """Check the transformed schema handed to the provider, not just local parsing."""

    def resolve(value: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in value:
            result: dict[str, Any] = schema["$defs"][value["$ref"].rsplit("/", 1)[-1]]
            return result
        return value

    candidate = resolve(schema["properties"]["candidates"]["items"])
    weights = resolve(candidate["properties"]["multipliers"])
    assert set(weights["properties"]) == {"Financial Sponsor", "Strategic"}
    assert set(weights["required"]) == set(weights["properties"])
    for value in weights["properties"].values():
        vector = resolve(value)
        assert set(vector["properties"]) == features
        assert set(vector["required"]) == features
        assert vector["additionalProperties"] is False


@pytest.mark.asyncio
async def test_proposal_is_one_recorded_call_and_replays_without_provider(
    deps: Deps,
    tmp_path: Path,
) -> None:
    weighting, policy = module_and_policy()
    module = import_module("evals.ranking.proposals")
    candidate = weighting.shared_candidate(deps.settings.scoring).model_copy(
        update={"name": "hypothesis"}
    )
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        assert info.output_tools
        assert_weight_fields(
            info.output_tools[0].parameters_json_schema, set(deps.settings.scoring.weights)
        )
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"candidates": [candidate.model_dump()]})
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=80),
        )

    services = build_services(deps, FunctionModel(respond), (), tmp_path, "propose", mode="test")
    packet = {"history_cutoff": 2018}
    first = await module.request_proposals(packet, deps.with_runtime(services), "propose", policy)
    replay = build_services(
        deps, None, (), tmp_path / "replay", "propose", mode="replay", cache_root=tmp_path / "cache"
    )
    second = await module.request_proposals(packet, deps.with_runtime(replay), "propose", policy)
    assert first == second
    assert calls == 1
    assert len(replay.model.ledger.entries) == 1
    assert replay.model.ledger.entries[0].cost_usd == 0


@pytest.mark.asyncio
async def test_invalid_proposal_does_not_trigger_another_request(
    deps: Deps, tmp_path: Path
) -> None:
    weighting, policy = module_and_policy()
    module = import_module("evals.ranking.proposals")
    candidate = weighting.shared_candidate(deps.settings.scoring)
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(info.output_tools[0].name, {"candidates": [candidate.model_dump()]})
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=80),
        )

    services = build_services(deps, FunctionModel(respond), (), tmp_path, "propose", mode="test")
    with pytest.raises(UnexpectedModelBehavior):
        await module.request_proposals({}, deps.with_runtime(services), "propose", policy)
    assert calls == 1
